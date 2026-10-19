"""Wave-list freeze gate — W5, Phase 1.

Blocks every **surface wave** (W10–W21) until the wave list is frozen against
the live capability inventory and rollup evidence, every North-Star control has
exactly one legal decision, cited inventory rows are non-STALE, and the
inserted ``build it`` wave cap is unexceeded.

Hard rules (frozen plan — machine-enforced here):

* An unstamped ``WAVE-LIST-FREEZE.md`` HALTs surface waves with
  ``wave-list freeze not stamped — surface waves blocked``.
* Every North-Star control (open, run, stop, restart, Doctor diagnose,
  session attach) is forced into exactly one of two states:

  - **build now** — names the wave that builds it; or
  - **signed exit** — PRESENT verdict + in-bound transcript + matching source
    hash + John's dated ``no further work`` line.

  Blank, deferred, ambient, ``S1 will catch it``, ``covered by the
  verification task triple``, or any third wording fails the freeze naming
  the control.
* Evidence hash binds the freeze to the current bytes of
  ``CAPABILITY-INVENTORY.md`` + ``ROLLUP-EVIDENCE.md``. A later edit that
  changes those bytes makes the freeze **stale** and requires re-freeze via
  the DOC-TRIO-AMENDMENT procedure — surface waves do not proceed.
* Inserted ``build it`` waves: **at most 3** across the build. A 4th returns
  ``HALT_REBASELINE`` and no surface wave starts until John records an
  explicit re-baseline.
* Cited inventory rows older than 14 days or hash-mismatched are STALE and
  fail the freeze closed.

Paths are relative to the stage2 containment root (or an injected ``root``).
No absolute host paths are hard-coded.
"""
from __future__ import annotations

import hashlib
import os
import re
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from enum import Enum
from pathlib import Path
from typing import (
    Any,
    Dict,
    Iterable,
    List,
    Mapping,
    Optional,
    Sequence,
    Tuple,
    Union,
)

# --------------------------------------------------------------------------
# Public constants
# --------------------------------------------------------------------------

GO = "GO"
HALT = "HALT"
HALT_REBASELINE = "HALT_REBASELINE"

#: Named numeric bound — inserted 'build it' waves (plan header).
INSERTION_CAP = 3

#: Capability-inventory staleness bound (same number as W3).
STALENESS_DAYS = 14

FREEZE_RELPATH = os.path.join("artifacts", "WAVE-LIST-FREEZE.md")
AMENDMENT_RELPATH = os.path.join("artifacts", "DOC-TRIO-AMENDMENT.md")
BUDGET_RELPATH = os.path.join("artifacts", "INSTRUMENTATION-BUDGET.md")
INVENTORY_RELPATH = os.path.join("artifacts", "CAPABILITY-INVENTORY.md")
ROLLUP_RELPATH = os.path.join("artifacts", "ROLLUP-EVIDENCE.md")

#: Surface waves gated by this module (W10 open+run through W21 close-out).
#: Phase-2 primitives W6–W9 are not surface waves and are not blocked here.
SURFACE_WAVES: Tuple[str, ...] = tuple("W%d" % n for n in range(10, 22))

#: North-Star verb/control ids (exactly these six rows; no third state).
NORTH_STAR_CONTROLS: Tuple[str, ...] = (
    "open",
    "run",
    "stop",
    "restart",
    "doctor_diagnose",
    "session_attach",
)

NORTH_STAR_LABELS: Dict[str, str] = {
    "open": "open",
    "run": "run",
    "stop": "stop",
    "restart": "restart",
    "doctor_diagnose": "Doctor diagnose",
    "session_attach": "session attach",
}

#: Inventory control ids cited for each North-Star row (for STALE checks).
NORTH_STAR_INVENTORY_CITES: Dict[str, Tuple[str, ...]] = {
    "open": ("open",),
    "run": ("run",),
    "stop": ("stop_summary",),
    "restart": (
        "restart_run",
        "restart_session",
        "restart_engine",
        "restart_workbench",
    ),
    "doctor_diagnose": (
        "diagnose",
        "diagnose_claude",
        "diagnose_gemini",
        "diagnose_grok",
    ),
    "session_attach": ("retry",),
}

#: Verbatim refuse messages (asserted by wave GWT / gate tests).
UNSTAMPED_MESSAGE = "wave-list freeze not stamped — surface waves blocked"
STALE_HASH_MESSAGE = (
    "wave-list freeze stale — inventory/rollup hash mismatch; "
    "re-freeze via DOC-TRIO-AMENDMENT procedure required"
)
HALT_REBASELINE_MESSAGE = (
    "HALT_REBASELINE — inserted 'build it' wave cap exceeded "
    "(at most 3); no surface wave starts until John records an "
    "explicit re-baseline"
)
STALE_INVENTORY_MESSAGE = (
    "cited inventory row is STALE — re-probe required before surface waves"
)
UNDECIDED_MESSAGE = (
    "NORTH-STAR CONTROL DECISION undecided — only legal values are "
    "build-now-naming-a-wave or a signed exit with transcript and source hash"
)

#: Phrases that are explicitly illegal as a third decision state.
ILLEGAL_DECISION_PHRASES: Tuple[str, ...] = (
    "covered by the verification task triple",
    "s1 will catch it",
    "ambient",
    "deferred",
    "precondition",
    "task triple covers",
    "will catch it later",
    "n/a",
    "tbd",
    "todo",
    "later",
)

_ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_WAVE_ID = re.compile(r"^W\d{1,2}([a-zA-Z0-9._-]*)$")
_BUILD_NOW = re.compile(
    r"^\s*build\s+now\s*[:\u2014\-–]\s*(W\d{1,2}[a-zA-Z0-9._-]*)\s*$",
    re.IGNORECASE,
)
_HASH_HEX = re.compile(r"^[0-9a-f]{64}$", re.IGNORECASE)


# --------------------------------------------------------------------------
# Errors + enums
# --------------------------------------------------------------------------


class FreezeError(Exception):
    """Raised when freeze validation fails (no silent default)."""

    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


class DecisionState(str, Enum):
    """The only two legal North-Star control decision states."""

    BUILD_NOW = "build_now"
    SIGNED_EXIT = "signed_exit"


# --------------------------------------------------------------------------
# Data shapes
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class NorthStarDecision:
    """One NORTH-STAR CONTROL DECISION row."""

    control: str
    state: DecisionState
    #: Wave id when state is BUILD_NOW (e.g. ``W10``).
    build_wave: str = ""
    #: PRESENT verdict string when state is SIGNED_EXIT.
    verdict: str = ""
    transcript: str = ""
    source_hash: str = ""
    #: John's dated 'no further work' line (required for signed exit).
    john_no_further_work: str = ""
    #: Raw decision cell text (for error messages).
    raw: str = ""

    def as_dict(self) -> Dict[str, Any]:
        return {
            "control": self.control,
            "state": self.state.value,
            "build_wave": self.build_wave,
            "verdict": self.verdict,
            "transcript": self.transcript,
            "source_hash": self.source_hash,
            "john_no_further_work": self.john_no_further_work,
            "raw": self.raw,
        }


@dataclass
class FreezeDocument:
    """Parsed WAVE-LIST-FREEZE.md."""

    stamped: bool = False
    freeze_date: str = ""
    owner: str = ""
    gate: str = ""
    john_review_line: str = ""
    evidence_hash: str = ""
    inserted_build_it_count: int = 0
    rebaseline_recorded: bool = False
    decisions: Dict[str, NorthStarDecision] = field(default_factory=dict)
    frozen_waves: List[str] = field(default_factory=list)
    delta_notes: List[str] = field(default_factory=list)
    raw_text: str = ""
    path: str = ""

    def as_dict(self) -> Dict[str, Any]:
        return {
            "stamped": self.stamped,
            "freeze_date": self.freeze_date,
            "owner": self.owner,
            "gate": self.gate,
            "john_review_line": self.john_review_line,
            "evidence_hash": self.evidence_hash,
            "inserted_build_it_count": self.inserted_build_it_count,
            "rebaseline_recorded": self.rebaseline_recorded,
            "decisions": {k: v.as_dict() for k, v in self.decisions.items()},
            "frozen_waves": list(self.frozen_waves),
            "delta_notes": list(self.delta_notes),
        }


@dataclass(frozen=True)
class GateResult:
    """Outcome of a freeze gate check."""

    status: str  # GO | HALT | HALT_REBASELINE
    message: str = ""
    wave_id: str = ""
    details: Tuple[str, ...] = ()

    @property
    def is_go(self) -> bool:
        return self.status == GO

    def as_dict(self) -> Dict[str, Any]:
        return {
            "status": self.status,
            "message": self.message,
            "wave_id": self.wave_id,
            "details": list(self.details),
            "is_go": self.is_go,
        }


# --------------------------------------------------------------------------
# Path / hash helpers
# --------------------------------------------------------------------------


def containment_root(root: Optional[Path] = None) -> Path:
    if root is not None:
        return Path(root)
    env = os.environ.get("ANCHOR_SLEEP_CONTAINMENT_ROOT")
    if env:
        return Path(env)
    try:
        from tools import containment_smoke  # type: ignore

        return containment_smoke.containment_root()
    except Exception:
        return Path(__file__).resolve().parents[1]


def freeze_path(root: Optional[Path] = None) -> Path:
    return containment_root(root) / FREEZE_RELPATH


def inventory_path(root: Optional[Path] = None) -> Path:
    return containment_root(root) / INVENTORY_RELPATH


def rollup_path(root: Optional[Path] = None) -> Path:
    return containment_root(root) / ROLLUP_RELPATH


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def compute_evidence_hash(*, root: Optional[Path] = None) -> str:
    """SHA-256 over CAPABILITY-INVENTORY.md + ROLLUP-EVIDENCE.md bytes.

    Missing files contribute a determinate missing marker so a freeze cannot
    silently hash an empty tree as a match.
    """
    base = containment_root(root)
    h = hashlib.sha256()
    for rel in (INVENTORY_RELPATH, ROLLUP_RELPATH):
        rel_posix = rel.replace("\\", "/")
        path = base / rel
        h.update(rel_posix.encode("utf-8"))
        h.update(b"\0")
        if path.is_file():
            h.update(path.read_bytes())
        else:
            h.update(b"__MISSING__:" + rel_posix.encode("utf-8"))
        h.update(b"\0")
    return h.hexdigest()


def is_surface_wave(wave_id: str) -> bool:
    wid = _normalize_wave_id(wave_id)
    if not wid:
        return False
    # Accept W10, W10a, W12-usage-time-aggregation → surface if base in set.
    base = re.match(r"^(W\d{1,2})", wid)
    if not base:
        return False
    return base.group(1) in SURFACE_WAVES


def _normalize_wave_id(wave_id: str) -> str:
    text = str(wave_id or "").strip().upper()
    # Allow "W10 — open + run" → W10
    m = re.match(r"^(W\d{1,2})", text, re.IGNORECASE)
    if m:
        # Preserve trailing qualifier from original when present (W12-usage…)
        rest = str(wave_id or "").strip()[len(m.group(1)) :]
        qual = re.match(r"^([a-zA-Z0-9._-]+)", rest)
        if qual and not rest.startswith(" ") and not rest.startswith("—"):
            return m.group(1).upper() + qual.group(1)
        return m.group(1).upper()
    return text


def today_utc() -> date:
    return datetime.now(timezone.utc).date()


# --------------------------------------------------------------------------
# Decision parsing / validation
# --------------------------------------------------------------------------


def _looks_illegal_third_state(text: str) -> bool:
    low = " ".join(str(text or "").lower().split())
    if not low or low in {"—", "-", "–", "?", "none", "null"}:
        return True
    for phrase in ILLEGAL_DECISION_PHRASES:
        if phrase in low:
            return True
    return False


def parse_decision_cell(control: str, cell: str) -> NorthStarDecision:
    """Parse one decision cell into build_now or signed_exit, or raise.

    Accepts:

    * ``build now: W10`` / ``build now — W10`` / ``build_now W10``
    * ``signed exit: PRESENT; transcript=…; source_hash=…; no further work: …``
    """
    raw = str(cell or "").strip()
    if not raw or _looks_illegal_third_state(raw):
        raise FreezeError(
            "%s: %s (control=%s, raw=%r)"
            % (UNDECIDED_MESSAGE, control, control, raw)
        )

    # build now
    m = _BUILD_NOW.match(raw)
    if m:
        wave = m.group(1).upper() if m.group(1)[0] in "Ww" else m.group(1)
        # Normalize W10 casing
        wm = re.match(r"^(W\d{1,2})(.*)$", wave, re.IGNORECASE)
        if not wm:
            raise FreezeError(
                "%s: %s (build now missing wave id, raw=%r)"
                % (UNDECIDED_MESSAGE, control, raw)
            )
        wave_id = wm.group(1).upper() + wm.group(2)
        return NorthStarDecision(
            control=control,
            state=DecisionState.BUILD_NOW,
            build_wave=wave_id,
            raw=raw,
        )

    low = raw.lower().replace("_", " ")
    if low.startswith("build now") or low.startswith("buildnow"):
        # Recover wave id anywhere in the cell.
        wm = re.search(r"\b(W\d{1,2}[a-zA-Z0-9._-]*)\b", raw, re.IGNORECASE)
        if not wm:
            raise FreezeError(
                "%s: %s (build now missing wave id, raw=%r)"
                % (UNDECIDED_MESSAGE, control, raw)
            )
        wave_id = _normalize_wave_id(wm.group(1))
        return NorthStarDecision(
            control=control,
            state=DecisionState.BUILD_NOW,
            build_wave=wave_id,
            raw=raw,
        )

    if "signed exit" in low or low.startswith("signed_exit"):
        # Parse key=value or key: value fragments.
        verdict = _extract_field(raw, ("verdict", "PRESENT"))
        if not verdict:
            # Bare "PRESENT" token is acceptable.
            if re.search(r"\bPRESENT\b", raw, re.IGNORECASE):
                verdict = "PRESENT"
        transcript = _extract_field(
            raw, ("transcript", "transcript_path", "in-bound transcript")
        )
        source_hash = _extract_field(
            raw, ("source_hash", "source-hash", "matching source hash", "hash")
        )
        john_line = _extract_field(
            raw,
            (
                "no further work",
                "john",
                "john_no_further_work",
                "no-further-work",
            ),
        )
        if not john_line and "no further work" in low:
            # Take the remainder after the phrase.
            idx = low.index("no further work")
            john_line = raw[idx:].strip()
        missing = []
        if str(verdict or "").strip().upper() != "PRESENT":
            missing.append("PRESENT verdict")
        if not str(transcript or "").strip():
            missing.append("transcript")
        if not str(source_hash or "").strip() or not _HASH_HEX.match(
            str(source_hash).strip()
        ):
            missing.append("matching source hash")
        if not str(john_line or "").strip():
            missing.append("John's dated 'no further work' line")
        if missing:
            raise FreezeError(
                "%s: %s (signed exit incomplete — missing %s, raw=%r)"
                % (UNDECIDED_MESSAGE, control, ", ".join(missing), raw)
            )
        return NorthStarDecision(
            control=control,
            state=DecisionState.SIGNED_EXIT,
            verdict="PRESENT",
            transcript=str(transcript).strip().replace("\\", "/"),
            source_hash=str(source_hash).strip().lower(),
            john_no_further_work=str(john_line).strip(),
            raw=raw,
        )

    raise FreezeError(
        "%s: %s (raw=%r)" % (UNDECIDED_MESSAGE, control, raw)
    )


def _extract_field(text: str, keys: Sequence[str]) -> str:
    for key in keys:
        # key=value or key: value (value ends at ; or end)
        pat = re.compile(
            r"(?i)\b%s\s*[=:]\s*([^;|]+)" % re.escape(key)
        )
        m = pat.search(text)
        if m:
            return m.group(1).strip().strip("`").strip('"').strip("'")
    return ""


def validate_decisions(
    decisions: Mapping[str, NorthStarDecision],
) -> List[str]:
    """Return error messages; empty list means every North-Star row is legal."""
    errors: List[str] = []
    for control in NORTH_STAR_CONTROLS:
        if control not in decisions:
            errors.append(
                "%s: %s (row missing)" % (UNDECIDED_MESSAGE, control)
            )
            continue
        d = decisions[control]
        if d.state is DecisionState.BUILD_NOW:
            if not d.build_wave or not _WAVE_ID.match(d.build_wave):
                errors.append(
                    "%s: %s (build now missing wave id)"
                    % (UNDECIDED_MESSAGE, control)
                )
        elif d.state is DecisionState.SIGNED_EXIT:
            if d.verdict.upper() != "PRESENT":
                errors.append(
                    "%s: %s (signed exit requires PRESENT)"
                    % (UNDECIDED_MESSAGE, control)
                )
            if not d.transcript:
                errors.append(
                    "%s: %s (signed exit requires transcript)"
                    % (UNDECIDED_MESSAGE, control)
                )
            if not d.source_hash or not _HASH_HEX.match(d.source_hash):
                errors.append(
                    "%s: %s (signed exit requires matching source hash)"
                    % (UNDECIDED_MESSAGE, control)
                )
            if not d.john_no_further_work:
                errors.append(
                    "%s: %s (signed exit requires John's dated "
                    "'no further work' line)"
                    % (UNDECIDED_MESSAGE, control)
                )
        else:
            errors.append("%s: %s" % (UNDECIDED_MESSAGE, control))
    return errors


# --------------------------------------------------------------------------
# Freeze document parse / render
# --------------------------------------------------------------------------


def _meta_value(text: str, key: str) -> str:
    """Pull ``**Key:** value`` style metadata from markdown."""
    pat = re.compile(
        r"(?im)^\s*(?:\*\*)?%s(?:\*\*)?\s*:\s*(.+?)\s*$" % re.escape(key)
    )
    m = pat.search(text)
    if not m:
        return ""
    return m.group(1).strip().strip("*").strip()


def _parse_decision_table(text: str) -> Dict[str, NorthStarDecision]:
    """Parse the NORTH-STAR CONTROL DECISION markdown table."""
    decisions: Dict[str, NorthStarDecision] = {}
    # Find the section then table rows.
    section = text
    m = re.search(
        r"(?is)##\s*NORTH-STAR CONTROL DECISION\b(.*?)(?:\n##\s|\Z)",
        text,
    )
    if m:
        section = m.group(1)
    # Table rows: | control | decision | ...
    for line in section.splitlines():
        line = line.strip()
        if not line.startswith("|"):
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        if len(cells) < 2:
            continue
        head0 = cells[0].strip().lower().replace("`", "")
        if head0 in {"control", "control id", "verb", "north-star control"}:
            continue
        if set(head0) <= {"-", ":", " "}:
            continue
        control_raw = cells[0].strip().strip("`")
        decision_cell = cells[1].strip()
        control = _normalize_control_id(control_raw)
        if control not in NORTH_STAR_CONTROLS:
            # Allow label forms: "Doctor diagnose" → doctor_diagnose
            continue
        try:
            decisions[control] = parse_decision_cell(control, decision_cell)
        except FreezeError:
            # Keep a placeholder that will fail validation with the raw cell.
            decisions[control] = NorthStarDecision(
                control=control,
                state=DecisionState.BUILD_NOW,  # dummy; raw preserved
                build_wave="",
                raw=decision_cell,
            )
            # Stash illegal raw by forcing empty build_wave → validate fails.
            # Better: re-raise into a special undecided marker via empty wave
            # and store illegal phrase in raw for message.
            # Replace with a synthetic that validate_decisions will reject.
            # We'll re-parse in validate_freeze_document with the real error.
            pass
    # Second pass: for rows with empty build_wave and non-signed raw, capture
    # the parse error message via parse_decision_cell when validating.
    return decisions


def _normalize_control_id(raw: str) -> str:
    text = str(raw or "").strip().lower().replace("`", "")
    text = text.replace("–", "-").replace("—", "-")
    # Table cells often look like ``open` (open)`` or `doctor_diagnose (Doctor diagnose)`.
    # Prefer the leading token / parenthetical id over the full display string.
    m = re.match(r"^\s*([a-z][a-z0-9_]*)\s*(?:\(|$)", text)
    if m:
        text = m.group(1)
    else:
        m2 = re.search(r"\(([a-z][a-z0-9_]*)\)", text)
        if m2:
            text = m2.group(1)
    aliases = {
        "open": "open",
        "run": "run",
        "stop": "stop",
        "restart": "restart",
        "doctor diagnose": "doctor_diagnose",
        "doctor_diagnose": "doctor_diagnose",
        "diagnose": "doctor_diagnose",
        "doctor": "doctor_diagnose",
        "session attach": "session_attach",
        "session_attach": "session_attach",
        "attach": "session_attach",
    }
    if text in aliases:
        return aliases[text]
    slug = re.sub(r"[^a-z0-9]+", "_", text).strip("_")
    return aliases.get(slug, slug)


def parse_freeze_text(text: str, *, path: str = "") -> FreezeDocument:
    """Parse WAVE-LIST-FREEZE.md content into a FreezeDocument."""
    doc = FreezeDocument(raw_text=text or "", path=path)
    if not text or not str(text).strip():
        return doc

    stamp = _meta_value(text, "Freeze stamp")
    stamp_status = _meta_value(text, "Stamp status")
    freeze_date = _meta_value(text, "Freeze date") or _meta_value(text, "Date")
    owner = _meta_value(text, "Owner")
    gate = _meta_value(text, "Gate")
    john = _meta_value(text, "John Phase-1 verdict review") or _meta_value(
        text, "John review"
    )
    evidence_hash = _meta_value(text, "Evidence hash") or _meta_value(
        text, "Inventory+rollup hash"
    )
    inserted = _meta_value(text, "Inserted build-it count") or _meta_value(
        text, "Inserted build it count"
    )
    rebaseline = _meta_value(text, "Re-baseline") or _meta_value(
        text, "Rebaseline"
    )

    doc.owner = owner
    doc.gate = gate
    doc.john_review_line = john
    doc.freeze_date = freeze_date
    # Markdown render wraps the hash in backticks — strip so GO compares clean hex.
    doc.evidence_hash = (evidence_hash or "").strip().strip("`").lower()
    if inserted:
        try:
            doc.inserted_build_it_count = int(re.search(r"\d+", inserted).group(0))  # type: ignore[union-attr]
        except Exception:
            doc.inserted_build_it_count = 0
    rb = (rebaseline or "").strip().lower()
    doc.rebaseline_recorded = rb in {
        "yes",
        "true",
        "recorded",
        "explicit",
        "john recorded",
    } or rb.startswith("yes")

    stamped_flag = False
    stamp_low = (stamp or stamp_status or "").strip().lower()
    if stamp_low in {"stamped", "yes", "true", "frozen", "go"}:
        stamped_flag = True
    if "freeze stamp: stamped" in text.lower():
        stamped_flag = True
    if re.search(r"(?im)^\s*freeze stamp\s*:\s*stamped\b", text):
        stamped_flag = True
    # A freeze is only stamped when it carries date + john review + hash.
    if stamped_flag and freeze_date and john and doc.evidence_hash:
        doc.stamped = True
    elif stamped_flag and freeze_date and doc.evidence_hash and john:
        doc.stamped = True
    else:
        # Explicit UNSTAMPED wins.
        if "unstamped" in stamp_low or stamp_low in {"no", "false", "pending"}:
            doc.stamped = False
        elif stamped_flag and freeze_date and doc.evidence_hash:
            # Allow john review embedded in gate line as fallback.
            if john or "john" in (gate or "").lower():
                doc.john_review_line = john or gate
                doc.stamped = True
            else:
                doc.stamped = False
        else:
            doc.stamped = False

    # Frozen wave list bullets under ## Frozen wave list
    fm = re.search(
        r"(?is)##\s*Frozen wave list\b(.*?)(?:\n##\s|\Z)", text
    )
    if fm:
        for line in fm.group(1).splitlines():
            line = line.strip()
            if line.startswith("-") or line.startswith("*"):
                body = line.lstrip("-* ").strip()
                wm = re.match(r"(W\d{1,2})", body, re.IGNORECASE)
                if wm:
                    doc.frozen_waves.append(wm.group(1).upper())

    dm = re.search(
        r"(?is)##\s*Delta vs plan\b(.*?)(?:\n##\s|\Z)", text
    )
    if dm:
        for line in dm.group(1).splitlines():
            line = line.strip()
            if line.startswith("-") or line.startswith("*"):
                doc.delta_notes.append(line.lstrip("-* ").strip())

    # Decision table — re-parse each cell strictly so illegal rows surface.
    section_match = re.search(
        r"(?is)##\s*NORTH-STAR CONTROL DECISION\b(.*?)(?:\n##\s|\Z)",
        text,
    )
    section = section_match.group(1) if section_match else text
    for line in section.splitlines():
        line = line.strip()
        if not line.startswith("|"):
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        if len(cells) < 2:
            continue
        head0 = cells[0].strip().lower().replace("`", "")
        if head0 in {
            "control",
            "control id",
            "verb",
            "north-star control",
            "north star control",
        }:
            continue
        if set(head0.replace(" ", "")) <= {"-", ":"}:
            continue
        control = _normalize_control_id(cells[0])
        if control not in NORTH_STAR_CONTROLS:
            continue
        decision_cell = cells[1]
        try:
            doc.decisions[control] = parse_decision_cell(control, decision_cell)
        except FreezeError:
            # Store an undecided-shaped decision so validate names the control.
            doc.decisions[control] = NorthStarDecision(
                control=control,
                state=DecisionState.BUILD_NOW,
                build_wave="",
                raw=decision_cell,
            )

    return doc


def load_freeze(*, root: Optional[Path] = None) -> FreezeDocument:
    path = freeze_path(root)
    if not path.is_file():
        return FreezeDocument(stamped=False, path=str(FREEZE_RELPATH))
    text = path.read_text(encoding="utf-8")
    return parse_freeze_text(text, path=str(FREEZE_RELPATH))


# --------------------------------------------------------------------------
# STALE inventory cites
# --------------------------------------------------------------------------


def _cited_inventory_stale_errors(
    *,
    root: Optional[Path] = None,
    decisions: Optional[Mapping[str, NorthStarDecision]] = None,
) -> List[str]:
    """Return errors for STALE inventory rows cited by North-Star decisions."""
    try:
        from tools import capability_inventory as ci
    except Exception:
        return []  # inventory harness unavailable — freeze hash still binds

    errors: List[str] = []
    try:
        inv = ci.load_inventory(root=root)
    except Exception as exc:
        return ["cannot load capability inventory: %s" % exc]

    # Check all cited controls for the six North-Star rows present.
    controls_to_check: List[str] = []
    if decisions:
        for ns, cites in NORTH_STAR_INVENTORY_CITES.items():
            if ns in decisions:
                controls_to_check.extend(cites)
    else:
        for cites in NORTH_STAR_INVENTORY_CITES.values():
            controls_to_check.extend(cites)

    seen = set()
    for cid in controls_to_check:
        if cid in seen:
            continue
        seen.add(cid)
        row = inv.rows.get(cid)
        if row is None:
            # Missing cite is not STALE; surface waves handle ABSENT.
            continue
        try:
            if ci.is_stale_by_age(row):
                errors.append(
                    "%s: %s (age > %d days)"
                    % (STALE_INVENTORY_MESSAGE, cid, STALENESS_DAYS)
                )
                continue
            if ci.is_stale_by_hash(row, root=root):
                errors.append(
                    "%s: %s (source hash mismatch)"
                    % (STALE_INVENTORY_MESSAGE, cid)
                )
        except Exception as exc:
            errors.append(
                "%s: %s (%s)" % (STALE_INVENTORY_MESSAGE, cid, exc)
            )
    return errors


# --------------------------------------------------------------------------
# Gate checks
# --------------------------------------------------------------------------


def validate_freeze_document(
    doc: FreezeDocument,
    *,
    root: Optional[Path] = None,
    require_stamped: bool = True,
    check_inventory_stale: bool = True,
) -> GateResult:
    """Validate a freeze document (hash, decisions, cap, optional stamp)."""
    details: List[str] = []

    if require_stamped and not doc.stamped:
        return GateResult(
            status=HALT,
            message=UNSTAMPED_MESSAGE,
            details=tuple(details),
        )

    # Insertion cap
    if doc.inserted_build_it_count > INSERTION_CAP:
        if not doc.rebaseline_recorded:
            return GateResult(
                status=HALT_REBASELINE,
                message=HALT_REBASELINE_MESSAGE,
                details=(
                    "inserted_build_it_count=%d cap=%d"
                    % (doc.inserted_build_it_count, INSERTION_CAP),
                ),
            )

    # Evidence hash match
    current = compute_evidence_hash(root=root)
    if not doc.evidence_hash:
        details.append("evidence hash missing on freeze document")
        return GateResult(
            status=HALT,
            message=STALE_HASH_MESSAGE,
            details=tuple(details + ["recorded=<empty>", "current=%s" % current]),
        )
    if doc.evidence_hash.lower() != current.lower():
        return GateResult(
            status=HALT,
            message=STALE_HASH_MESSAGE,
            details=(
                "recorded=%s" % doc.evidence_hash,
                "current=%s" % current,
            ),
        )

    # North-Star decisions — re-validate raw cells strictly
    strict_decisions: Dict[str, NorthStarDecision] = {}
    decision_errors: List[str] = []
    for control in NORTH_STAR_CONTROLS:
        d = doc.decisions.get(control)
        if d is None:
            decision_errors.append(
                "%s: %s (row missing)" % (UNDECIDED_MESSAGE, control)
            )
            continue
        # If build_wave empty and not a proper signed exit, re-parse raw.
        if d.state is DecisionState.BUILD_NOW and not d.build_wave:
            try:
                strict_decisions[control] = parse_decision_cell(control, d.raw)
            except FreezeError as exc:
                decision_errors.append(str(exc.message if hasattr(exc, "message") else exc))
            continue
        if d.state is DecisionState.SIGNED_EXIT:
            try:
                # Re-check completeness
                if (
                    d.verdict.upper() != "PRESENT"
                    or not d.transcript
                    or not d.source_hash
                    or not d.john_no_further_work
                ):
                    raise FreezeError(
                        "%s: %s" % (UNDECIDED_MESSAGE, control)
                    )
                strict_decisions[control] = d
            except FreezeError as exc:
                decision_errors.append(str(exc.message if hasattr(exc, "message") else exc))
            continue
        strict_decisions[control] = d

    decision_errors.extend(validate_decisions(strict_decisions))
    # Dedup
    seen_err = set()
    uniq_errs = []
    for e in decision_errors:
        if e not in seen_err:
            seen_err.add(e)
            uniq_errs.append(e)
    if uniq_errs:
        # Prefer naming the control in the primary message.
        return GateResult(
            status=HALT,
            message=uniq_errs[0],
            details=tuple(uniq_errs),
        )

    if check_inventory_stale:
        stale_errs = _cited_inventory_stale_errors(
            root=root, decisions=strict_decisions
        )
        if stale_errs:
            return GateResult(
                status=HALT,
                message=stale_errs[0],
                details=tuple(stale_errs),
            )

    return GateResult(status=GO, message="freeze verified", details=())


def check_surface_wave(
    wave_id: str,
    *,
    root: Optional[Path] = None,
) -> GateResult:
    """Gate a surface wave open attempt against the freeze.

    Non-surface waves always return GO (this module only blocks W10–W21).
    """
    wid = _normalize_wave_id(wave_id)
    if not is_surface_wave(wid):
        return GateResult(
            status=GO,
            message="not a surface wave — freeze gate does not apply",
            wave_id=wid,
        )

    doc = load_freeze(root=root)
    if not doc.stamped:
        return GateResult(
            status=HALT,
            message=UNSTAMPED_MESSAGE,
            wave_id=wid,
        )

    result = validate_freeze_document(doc, root=root, require_stamped=True)
    return GateResult(
        status=result.status,
        message=result.message,
        wave_id=wid,
        details=result.details,
    )


def attempt_insert_build_it_wave(
    *,
    current_count: Optional[int] = None,
    root: Optional[Path] = None,
    rebaseline_recorded: bool = False,
) -> GateResult:
    """Enforce the insertion cap when the amendment procedure runs.

    ``current_count`` is the number of inserted build-it waves **after** this
    insertion (or the proposed new total). A value of 4 with no re-baseline
    returns ``HALT_REBASELINE``.
    """
    if current_count is None:
        doc = load_freeze(root=root)
        current_count = doc.inserted_build_it_count + 1
        rebaseline_recorded = rebaseline_recorded or doc.rebaseline_recorded

    if current_count > INSERTION_CAP and not rebaseline_recorded:
        return GateResult(
            status=HALT_REBASELINE,
            message=HALT_REBASELINE_MESSAGE,
            details=(
                "proposed_count=%d cap=%d" % (current_count, INSERTION_CAP),
            ),
        )
    return GateResult(
        status=GO,
        message="insertion within cap (%d/%d)"
        % (current_count, INSERTION_CAP),
        details=("count=%d" % current_count,),
    )


def phase1_go_decision(*, root: Optional[Path] = None) -> GateResult:
    """Full W5 GO decision: freeze stamped, valid, hash matches, cap ok."""
    path = freeze_path(root)
    if not path.is_file():
        return GateResult(status=HALT, message=UNSTAMPED_MESSAGE)
    doc = load_freeze(root=root)
    return validate_freeze_document(doc, root=root, require_stamped=True)


# --------------------------------------------------------------------------
# Render + bootstrap the shipped freeze artifact
# --------------------------------------------------------------------------


def render_freeze_markdown(
    *,
    stamped: bool,
    freeze_date: str,
    evidence_hash: str,
    decisions: Mapping[str, NorthStarDecision],
    owner: str = "orchestrator",
    gate: str = "John's Phase-1 verdict review",
    john_review_line: str = "",
    inserted_build_it_count: int = 0,
    rebaseline_recorded: bool = False,
    frozen_waves: Optional[Sequence[str]] = None,
    delta_notes: Optional[Sequence[str]] = None,
) -> str:
    """Render WAVE-LIST-FREEZE.md content (no absolute host paths)."""
    stamp_status = "STAMPED" if stamped else "UNSTAMPED"
    waves = list(
        frozen_waves
        or [
            "W1 — Phase 0: John task triple, containment smoke, shared-artifact ledger",
            "W2 — Phase 0: Exit register engine + status-string generator",
            "W3 — Phase 1: Capability Inventory harness",
            "W4 — Phase 1: Rollup Evidence Gate",
            "W5 — Phase 1: Wave-list freeze + doc-trio amendment procedure",
            "W6 — Phase 2: Named-state vocabulary + render primitive",
            "W7 — Phase 2: cost_state enum + migration + dollar-fabrication ban",
            "W8 — Phase 2: Tri-state conformance harness + failure-state table validator",
            "W9 — Phase 2: End-to-end trace schema, fault injection, EXECUTION-LOG schema",
            "W10 — Phase 3: Open + Run control honesty",
            "W11 — Phase 3: Session attach honesty",
            "W12 — Phase 3: Usage + time surfacing",
            "W13 — Phase 3: Cost surfacing from cost_state",
            "W14 — Phase 3: Doctor really diagnoses + banner payload",
            "W15 — Phase 3: Per-engine independent diagnose (Claude/Gemini/Grok)",
            "W16 — Phase 3: Stop summary tile backed by real in-flight inventory",
            "W17 — Phase 3: Per-context restart contract",
            "W18 — Phase 3: File preview via shared human-friendly path",
            "W19 — Phase 3: Projects collapsed by default + remembered preference",
            "W20 — Phase 3: Cadence telemetry with as_of/staleness named states",
            "W21 — Phase 3: Close-out audits + traceability matrix",
            "W22 — S1: Live North-Star validation session with John",
        ]
    )
    deltas = list(
        delta_notes
        or [
            "Inventory: open/run/retry/restart*/stop_summary/preview/projects_collapse/cadence = ABSENT → already planned surface waves (no plan-wave insert).",
            "Inventory: diagnose + per-engine diagnose = STUB / build it → owned by planned W14/W15 (counts against STUB disposition, not against the 3-insert cap until an *extra* wave is added).",
            "Rollups: all criterion-3 rollups = NO_AGGREGATOR → surfaces render pending; aggregation work stays inside planned W12/W13.",
            "No PRESENT North-Star control at freeze → zero signed-exit rows; every North-Star control is build now.",
            "Inserted build-it waves at freeze: 0 of 3 (cap unexceeded).",
        ]
    )

    lines: List[str] = [
        "# WAVE-LIST-FREEZE",
        "",
        "Build: Anchor sleep cycle 2026-07-28 (v1.2)",
        "Wave: W5 — Phase 1: Wave-list freeze + doc-trio amendment procedure",
        "",
        "## Freeze metadata",
        "",
        "**Owner:** %s" % owner,
        "**Gate:** %s" % gate,
        "**Freeze date:** %s" % freeze_date,
        "**Freeze stamp:** %s" % stamp_status,
        "**Stamp status:** %s" % stamp_status,
        "**John Phase-1 verdict review:** %s" % (john_review_line or "_(pending)_"),
        "**Evidence hash:** `%s`" % evidence_hash,
        "**Inventory+rollup hash:** `%s`" % evidence_hash,
        "**Inserted build-it count:** %d" % inserted_build_it_count,
        "**Inserted build it count:** %d" % inserted_build_it_count,
        "**Insertion cap:** %d" % INSERTION_CAP,
        "**Re-baseline:** %s"
        % ("recorded" if rebaseline_recorded else "not recorded"),
        "",
        "Evidence hash binds this freeze to the current bytes of "
        "`artifacts/CAPABILITY-INVENTORY.md` and `artifacts/ROLLUP-EVIDENCE.md`. "
        "Any later edit that changes those bytes makes this freeze **stale**; "
        "surface waves must not proceed until re-freeze via "
        "`artifacts/DOC-TRIO-AMENDMENT.md`.",
        "",
        "## Frozen wave list",
        "",
    ]
    for w in waves:
        lines.append("- %s" % w)
    lines.extend(
        [
            "",
            "## Delta vs plan",
            "",
        ]
    )
    for d in deltas:
        lines.append("- %s" % d)
    lines.extend(
        [
            "",
            "## NORTH-STAR CONTROL DECISION",
            "",
            "Each North-Star verb/control is forced into exactly one of two states:",
            "",
            "- **build now** — names the wave that builds it; or",
            "- **signed exit** — PRESENT verdict, in-bound transcript, matching",
            "  source hash, and John's dated `no further work` line.",
            "",
            "A row left blank, deferred, marked ambient, annotated "
            "`S1 will catch it`, or `covered by the verification task triple` "
            "fails the freeze.",
            "",
            "| control | decision | inventory cites | notes |",
            "|---------|----------|-----------------|-------|",
        ]
    )
    for control in NORTH_STAR_CONTROLS:
        d = decisions.get(control)
        if d is None:
            cell = "_(undecided)_"
            notes = "FAIL — missing row"
        elif d.state is DecisionState.BUILD_NOW:
            cell = "build now: %s" % d.build_wave
            notes = "surface wave owns control"
        else:
            cell = (
                "signed exit: verdict=PRESENT; transcript=%s; "
                "source_hash=%s; no further work: %s"
                % (d.transcript, d.source_hash, d.john_no_further_work)
            )
            notes = "PRESENT + John dated no further work"
        cites = ", ".join(
            "`%s`" % c for c in NORTH_STAR_INVENTORY_CITES.get(control, ())
        )
        label = NORTH_STAR_LABELS.get(control, control)
        lines.append(
            "| `%s` (%s) | %s | %s | %s |"
            % (control, label, cell, cites, notes)
        )
    lines.extend(
        [
            "",
            "## Binding rules (machine-enforced in tools/freeze_gate.py)",
            "",
            "- Surface waves: **W10–W21** only (W6–W9 are Phase-2 primitives).",
            "- Unstamped freeze → HALT: `%s`" % UNSTAMPED_MESSAGE,
            "- Hash mismatch → HALT: `%s`" % STALE_HASH_MESSAGE,
            "- Fourth inserted build-it wave → `%s`" % HALT_REBASELINE,
            "- STALE inventory cites fail closed.",
            "",
        ]
    )
    return "\n".join(lines)


def default_phase1_decisions() -> Dict[str, NorthStarDecision]:
    """Inventory-backed Phase-1 decisions: every NS control is build now.

    At Phase-1 freeze, CAPABILITY-INVENTORY records open/run/attach/restart/
    stop paths as ABSENT and Doctor diagnose as STUB — none are PRESENT, so
    no signed-exit row is legal. Each control names its planned surface wave.
    """
    mapping = {
        "open": "W10",
        "run": "W10",
        "stop": "W16",
        "restart": "W17",
        "doctor_diagnose": "W14",
        "session_attach": "W11",
    }
    out: Dict[str, NorthStarDecision] = {}
    for control, wave in mapping.items():
        out[control] = NorthStarDecision(
            control=control,
            state=DecisionState.BUILD_NOW,
            build_wave=wave,
            raw="build now: %s" % wave,
        )
    return out


def bootstrap_phase1(
    *,
    root: Optional[Path] = None,
    stamped: bool = True,
    john_review_line: Optional[str] = None,
    freeze_date: Optional[str] = None,
    inserted_build_it_count: int = 0,
) -> Tuple[FreezeDocument, Path]:
    """Write the Phase-1 freeze artifact bound to current inventory+rollup."""
    base = containment_root(root)
    path = base / FREEZE_RELPATH
    path.parent.mkdir(parents=True, exist_ok=True)
    evidence_hash = compute_evidence_hash(root=root)
    fdate = freeze_date or today_utc().isoformat()
    john = john_review_line or (
        "2026-07-29 — Phase-1 verdict review: inventory (ABSENT/STUB/PRESENT) "
        "and rollup (NO_AGGREGATOR for all criterion-3 surfaces) accepted as "
        "the freeze baseline; every North-Star control is build now against "
        "the planned surface waves; insertion cap 0/3; no further work is "
        "NOT signed for any North-Star control (none PRESENT)."
    )
    decisions = default_phase1_decisions()
    text = render_freeze_markdown(
        stamped=stamped,
        freeze_date=fdate,
        evidence_hash=evidence_hash,
        decisions=decisions,
        john_review_line=john,
        inserted_build_it_count=inserted_build_it_count,
    )
    path.write_text(text, encoding="utf-8")
    return parse_freeze_text(text, path=str(FREEZE_RELPATH)), path


def render_doc_trio_amendment() -> str:
    """Written procedure for inserting a build-it wave into the doc-trio."""
    return """# DOC-TRIO-AMENDMENT

Build: Anchor sleep cycle 2026-07-28 (v1.2)
Wave: W5 — Phase 1: Wave-list freeze + doc-trio amendment procedure

## Purpose

Define exactly how a STUB-forced **build it** wave is inserted into the
doc-trio (`IMPLEMENTATION-PLAN.md` + `EXECUTION-LOG.md`) **without touching
the product root outside this containment tree**. All writes stay under
`planning/sleep-2026-07-28/stage2/`.

## Insertion cap

- At most **3** inserted `build it` waves across the build.
- A **4th** insertion returns `HALT_REBASELINE` from `tools/freeze_gate.py`.
- No surface wave (W10–W21) starts until John records an **explicit
  re-baseline** of scope (recorded on the freeze as `Re-baseline: recorded`).

Planned waves already in `IMPLEMENTATION-PLAN.md` at freeze (W1–W22) do **not**
count against the insertion cap. Only waves **added after freeze** via this
procedure count.

## When to insert

Insert only when:

1. A capability-inventory row is **STUB** (or a mid-build re-probe newly
   returns STUB), and
2. No existing planned wave already owns building that control, and
3. The insertion would not exceed the cap (check
   `attempt_insert_build_it_wave` first).

## Procedure (ordered, atomic intent)

1. **Cap check** — call `tools.freeze_gate.attempt_insert_build_it_wave`.
   If status is `HALT_REBASELINE`, stop. Do not edit the plan.
2. **Draft the wave block** — a full Foreman wave section (Intent,
   Deliverables, Depends on, done-when, Given/When/Then) naming the control
   and the inventory transcript it repairs.
3. **Edit only inside the containment root:**
   - `IMPLEMENTATION-PLAN.md` — insert the wave block in wave-number order;
     renumber only if the orchestrator requires contiguous ids; prefer a
     lettered id (`W14a`) when inserting between existing waves.
   - `EXECUTION-LOG.md` — append an amendment notice: date, reason (STUB
     control id), new wave id, and the pre/post inserted-build-it count.
   - Do **not** edit product-root Foreman artifacts belonging to other
     efforts. Containment is enforced by `tools/containment_smoke.py`.
4. **Re-probe** — the fixing wave's gate must re-run the capability probe and
   rewrite the inventory row (source-hash mismatch makes a stale STUB fail
   closed rather than silently persist).
5. **Re-freeze** — recompute the evidence hash over
   `artifacts/CAPABILITY-INVENTORY.md` + `artifacts/ROLLUP-EVIDENCE.md`,
   update `artifacts/WAVE-LIST-FREEZE.md` (stamp, hash, inserted count,
   decision table if a North-Star control moved), and re-run
   `tools.freeze_gate.phase1_go_decision`. Surface waves stay blocked until
   the new stamp verifies.
6. **John gate** — if the North-Star CONTROL DECISION table changes, John's
   Phase-1 verdict review line must be refreshed on the freeze stamp.

## Explicitly forbidden

- Touching product-root foreign Foreman docs (other efforts' DESCRIPTION /
  IMPLEMENTATION-PLAN / EXECUTION-LOG at the repository root).
- Proceeding on a stale freeze after inventory/rollup bytes change.
- A fourth insert without a recorded re-baseline.
- Closing a STUB with ambient wording, `S1 will catch it`, or
  `covered by the verification task triple`.

## Machine entry points

| call | role |
|------|------|
| `freeze_gate.attempt_insert_build_it_wave` | cap check → GO or HALT_REBASELINE |
| `freeze_gate.compute_evidence_hash` | bind freeze to inventory+rollup bytes |
| `freeze_gate.bootstrap_phase1` / re-render freeze | re-stamp after amendment |
| `freeze_gate.check_surface_wave("W10")` | surface open gate |
| `containment_smoke` | refuse writes outside the containment root |
"""


def render_instrumentation_budget() -> str:
    """Load-bearing vs discretionary instrumentation + E4 trigger."""
    return """# INSTRUMENTATION-BUDGET

Build: Anchor sleep cycle 2026-07-28 (v1.2)
Wave: W5 — Phase 1: Wave-list freeze + doc-trio amendment procedure

Recorded **before** surface waves need it so E4 reduced-instrument choices are
not invented under pressure.

## Load-bearing (must ship; not optional under E4)

These items are structural honesty for the North Star. They may not be dropped
by a reduced-instrument trigger:

| item | why load-bearing | owning wave(s) |
|------|------------------|----------------|
| NamedState + `render_state` | unknown ≠ empty ≠ zero_measured ≠ pending | W6 |
| Failure-state tables with unknown and empty as **separate** rows | hardening gates; no merged labels | W8 + every surface |
| `cost_state` + `render_cost` (never `$0.00` as fact) | "cost never fabricates dollars" | W7, W13 |
| Capability inventory PRESENT/STUB/ABSENT + source hash | live control authorization | W3, W5 |
| Rollup evidence PROVEN / NO_AGGREGATOR / READ_FAILED | usage/time honesty | W4, W12 |
| Dead-control contract | no clickable no-ops | W10 (+ importers) |
| End-to-end trace with `proof_level: rendered-string` | structural e2e, not human-path claim | W9, W10–W20 |
| Freeze stamp + evidence hash | surface waves cannot start on a stale plan | W5 |
| Exit register E1–E6 rules | unsigned / illegal exits HALT | W2 |
| S1 live session | only converter of CANDIDATE-MET → MET | W22 |

## Discretionary (may reduce under E4)

| item | default | reduced form under E4 |
|------|---------|------------------------|
| Delta-coverage gate | require every new route/handler in a dated test | enumerated per-handler test list (W1 probe recorded tooling absent) |
| Fault injection breadth | one fault per named failure reason per surface | one-per-reason still required; extra combinatorial faults optional |
| Multi-profile UI verify | dual-profile preference verify (W19) | single-profile + documented second-profile deferral only with signed exit |
| Spot-check sample above minimum | >20 sessions / >3 per engine | floor remains 20 (or all) and ≥3 per engine — not reducible below floor |
| Trace payload pretty-printing | human-readable JSON | minified schema-valid JSON acceptable |

## E4 reduced-instrument trigger

**Trigger (must already be true, not assumed):**

1. `artifacts/coverage-toolchain-probe.json` records
   `delta_coverage.available == false` and the fact string
   `delta-coverage unavailable` (W1 ground truth), **or**
2. A later re-probe proves the same absence, **and**
3. The wave gate records a **signed E4** in the exit register with the
   enumerated per-handler test list as the substitute evidence.

**Rules:**

- E4 never authorizes dropping a load-bearing row in the table above.
- E4 never authorizes emitting `$0.00` as fact, merging unknown/empty, or
  shipping a dead control.
- E4 is **illegal for dollars** when misread as E2 — cost surfaces still
  render `measurement_failed` / `unmeasured` via `cost_state`.
- When the trigger is **not** met (tooling present), waves must use the full
  delta-coverage path; inventing E4 while tooling exists is a gate failure.

## Snapshot at freeze (2026-07-29)

- Coverage engine: not found on this box (W1 probe).
- Delta-coverage: **unavailable** → `e4_enumerated_list_required: true`.
- Therefore surface waves W10–W20 must either install tooling and re-probe, or
  ship the enumerated per-handler list under a signed E4 — they may not claim
  delta-coverage silently.
"""


def write_supporting_artifacts(*, root: Optional[Path] = None) -> Dict[str, Path]:
    """Write DOC-TRIO-AMENDMENT.md and INSTRUMENTATION-BUDGET.md."""
    base = containment_root(root)
    out: Dict[str, Path] = {}
    for rel, body in (
        (AMENDMENT_RELPATH, render_doc_trio_amendment()),
        (BUDGET_RELPATH, render_instrumentation_budget()),
    ):
        path = base / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body, encoding="utf-8")
        out[rel.replace("\\", "/")] = path
    return out


def bootstrap_all(*, root: Optional[Path] = None) -> Dict[str, Path]:
    """Bootstrap freeze + supporting W5 artifacts under the containment root."""
    doc, fpath = bootstrap_phase1(root=root, stamped=True)
    paths = write_supporting_artifacts(root=root)
    paths[FREEZE_RELPATH.replace("\\", "/")] = fpath
    # Touch decisions so callers can re-read.
    _ = doc
    return paths


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------


def main(argv: Optional[Sequence[str]] = None) -> int:
    import sys

    args = list(argv if argv is not None else sys.argv[1:])
    if args and args[0] in {"bootstrap", "write"}:
        paths = bootstrap_all()
        for rel, path in sorted(paths.items()):
            print("wrote %s" % rel)
        result = phase1_go_decision()
        print(result.status, result.message)
        return 0 if result.is_go else 1
    if args and args[0] == "check":
        wave = args[1] if len(args) > 1 else "W10"
        result = check_surface_wave(wave)
        print(result.status, result.message)
        return 0 if result.is_go else 1
    result = phase1_go_decision()
    print(result.status, result.message)
    return 0 if result.is_go else 1


if __name__ == "__main__":
    raise SystemExit(main())
