"""Capability Inventory harness — W3, Phase 1.

Produces the artifact that decides what every surface wave is allowed to claim:
for each control named by the ten criteria (plus open and run), a tri-state
verdict backed by a transcript, so "wire it" can be reclassified to "build it"
or to a signed E1.

Hard rules (frozen plan — machine-enforced here):

* Verdicts are exactly ``PRESENT`` | ``STUB`` | ``ABSENT``.
* **STUB is never auto-downgraded to ABSENT** — a reclassification that would
  lower STUB to ABSENT is refused by name.
* Every verdict requires a non-empty transcript reference and a SHA-256 of the
  source file(s) under test. A row without either is ``verdict without
  evidence`` naming the control — never a silent default to ABSENT or PRESENT.
* A row older than **14 days**, or whose recorded source hash no longer matches
  the code at HEAD, is **STALE**. STALE fails closed: treated as UNKNOWN, not
  as its last verdict, and it may not authorize rendering any live control
  until re-probed.
* Replay authority: a PRESENT established only by replaying a stored transcript
  may authorize *documentation*, never the *shipping of a live control*.
  Shipping requires a **live** probe inside the staleness bound against a
  matching source hash.
* STUB disposition is always ``build it`` (never ``wire it``, never E1).

Paths are relative to the stage2 containment root (or an injected ``root``).
No absolute host paths are hard-coded.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timedelta, timezone
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

#: Named numeric bound — capability-inventory staleness bound (plan header).
STALENESS_DAYS = 14

GO = "GO"
HALT = "HALT"

#: Document relative path under the containment root.
INVENTORY_RELPATH = os.path.join("artifacts", "CAPABILITY-INVENTORY.md")
TRANSCRIPTS_RELDIR = os.path.join("artifacts", "transcripts")

#: Verbatim refuse messages (asserted by the wave GWT / gate tests).
VERDICT_WITHOUT_EVIDENCE = "verdict without evidence"
STUB_TO_ABSENT_MESSAGE = (
    "STUB cannot be auto-downgraded to ABSENT — re-probe required; "
    "STUB routes to 'build it', never silent ABSENT"
)
REPLAY_LIVE_REFUSE_MESSAGE = (
    "PRESENT from replay may authorize documentation only — "
    "shipping a live control requires a live probe inside the 14-day bound "
    "against a matching source hash"
)
STALE_REPROBE_MESSAGE = (
    "STALE inventory row — re-probe required; fail-closed as UNKNOWN "
    "(may not authorize any live control)"
)

#: Evidence modes.
EVIDENCE_LIVE = "live"
EVIDENCE_REPLAY = "replay"

#: Disposition strings (routing constrained by the master plan).
DISPOSITION_WIRE_IT = "wire it"
DISPOSITION_BUILD_IT = "build it"
DISPOSITION_E1_CANDIDATE = "E1 candidate"  # ABSENT only; signing is W2's job

_ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_ISO_DATETIME = re.compile(
    r"^\d{4}-\d{2}-\d{2}([T ]\d{2}:\d{2}:\d{2}(\.\d+)?(Z|[+-]\d{2}:\d{2})?)?$"
)

# --------------------------------------------------------------------------
# Canonical control ids (criteria 1–8 + open + run + per-engine diagnose)
# --------------------------------------------------------------------------

#: Stable control ids this inventory must cover. Order is the document order.
REQUIRED_CONTROLS: Tuple[str, ...] = (
    "open",
    "run",
    "retry",
    "diagnose",
    "restart_run",
    "restart_session",
    "restart_engine",
    "restart_workbench",
    "stop_summary",
    "preview_path",
    "projects_collapse",
    "cadence_telemetry",
    "diagnose_claude",
    "diagnose_gemini",
    "diagnose_grok",
)

CONTROL_LABELS: Dict[str, str] = {
    "open": "open control",
    "run": "run control",
    "retry": "Retry (session attach)",
    "diagnose": "Diagnose (Doctor)",
    "restart_run": "restart control — run context",
    "restart_session": "restart control — session context",
    "restart_engine": "restart control — engine context",
    "restart_workbench": "restart control — workbench context",
    "stop_summary": "stop-summary inventory source",
    "preview_path": "preview path",
    "projects_collapse": "projects-collapse handler",
    "cadence_telemetry": "cadence telemetry source",
    "diagnose_claude": "Diagnose — Claude engine",
    "diagnose_gemini": "Diagnose — Gemini engine",
    "diagnose_grok": "Diagnose — Grok engine",
}


# --------------------------------------------------------------------------
# Enums + errors
# --------------------------------------------------------------------------


class Verdict(str, Enum):
    """Tri-state capability verdict — the only legal values on a row."""

    PRESENT = "PRESENT"
    STUB = "STUB"
    ABSENT = "ABSENT"


class EffectiveState(str, Enum):
    """Resolved state after staleness / hash checks.

    STALE and UNKNOWN fail closed: they are never treated as the last recorded
    PRESENT/STUB/ABSENT verdict for authorization.
    """

    PRESENT = "PRESENT"
    STUB = "STUB"
    ABSENT = "ABSENT"
    STALE = "STALE"
    UNKNOWN = "UNKNOWN"


class InventoryError(Exception):
    """Raised when an inventory rule is violated (no silent default)."""

    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


class VerdictWithoutEvidence(InventoryError):
    """No transcript / no source hash — gate fails naming the control."""


class IllegalReclassification(InventoryError):
    """STUB→ABSENT (or other illegal verdict transition) refused."""


class StaleInventory(InventoryError):
    """Row is STALE / fail-closed; surface waves must re-probe."""


# --------------------------------------------------------------------------
# Probe observation + row schema
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class ProbeObservation:
    """What a probe saw for one control.

    Classification rules (binding):

    * handler bound + returns canned/seed output → STUB
    * no handler and no capability → ABSENT
    * handler bound + real (non-canned) capability path with observable → PRESENT
    """

    control_id: str
    handler_bound: bool = False
    returns_canned_seed: bool = False
    capability_callable: bool = False
    external_observable: bool = False
    notes: str = ""
    #: Raw probe output excerpt (recorded into the transcript).
    output_excerpt: str = ""


@dataclass(frozen=True)
class InventoryRow:
    """One capability-inventory row: control, verdict, transcript, hashes.

    Frozen so a re-probe against an unchanged source hash can return a
    byte-identical serialization (idempotence gate).
    """

    control_id: str
    verdict: Verdict
    transcript_path: str
    source_paths: Tuple[str, ...]
    source_hash: str
    probe_date: str
    evidence_mode: str  # live | replay
    disposition: str
    notes: str = ""
    label: str = ""

    def as_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["verdict"] = self.verdict.value
        d["source_paths"] = list(self.source_paths)
        return d

    def canonical_bytes(self) -> bytes:
        """Stable serialization for idempotence / equality checks."""
        payload = self.as_dict()
        return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode(
            "utf-8"
        )


@dataclass(frozen=True)
class ResolvedRow:
    """A row after staleness + hash-match resolution."""

    row: InventoryRow
    effective: EffectiveState
    age_days: int
    hash_matches: bool
    is_stale: bool
    stale_reasons: Tuple[str, ...]

    @property
    def fails_closed(self) -> bool:
        return self.is_stale or self.effective in {
            EffectiveState.STALE,
            EffectiveState.UNKNOWN,
        }


# --------------------------------------------------------------------------
# Path / date / hash helpers
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
        # tools/capability_inventory.py → stage2 root is parents[1]
        return Path(__file__).resolve().parents[1]


def inventory_path(root: Optional[Path] = None) -> Path:
    return containment_root(root) / INVENTORY_RELPATH


def transcripts_dir(root: Optional[Path] = None) -> Path:
    return containment_root(root) / TRANSCRIPTS_RELDIR


def parse_verdict(value: Union[Verdict, str]) -> Verdict:
    if isinstance(value, Verdict):
        return value
    text = str(value).strip().upper()
    try:
        return Verdict[text]
    except KeyError as exc:
        raise InventoryError(
            "unknown verdict %r — only PRESENT | STUB | ABSENT are legal" % value
        ) from exc


def parse_probe_date(value: Union[str, date, datetime]) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value).strip()
    if not text:
        raise InventoryError("probe_date is required")
    # Accept full ISO datetime; take the date part.
    if "T" in text or " " in text:
        text = text.replace("Z", "+00:00")
        try:
            return datetime.fromisoformat(text).date()
        except ValueError:
            text = text[:10]
    if not _ISO_DATE.match(text):
        raise InventoryError("probe_date must be ISO YYYY-MM-DD, got %r" % value)
    y, m, d = (int(p) for p in text.split("-"))
    return date(y, m, d)


def today_utc() -> date:
    return datetime.now(timezone.utc).date()


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def hash_sources(
    source_paths: Sequence[str],
    *,
    root: Optional[Path] = None,
    content_overrides: Optional[Mapping[str, bytes]] = None,
) -> str:
    """SHA-256 over source file contents under ``root`` (path-sorted).

    Paths are recorded on the inventory row for identity; the hash binds the
    row to the **bytes under test**. Order is sorted by relative path so the
    digest is stable. Missing files contribute a determinate missing marker
    so a deleted source still produces a hash (which then mismatches HEAD).

    Empty content hashes to the well-known empty digest when every listed
    source is an empty file — useful for ABSENT rows with probe markers.
    """
    base = containment_root(root)
    overrides = dict(content_overrides or {})
    h = hashlib.sha256()
    for rel in sorted(str(p).replace("\\", "/") for p in source_paths):
        if rel in overrides:
            body = overrides[rel]
        else:
            path = base / rel
            if path.is_file():
                body = path.read_bytes()
            else:
                body = b"__MISSING__:" + rel.encode("utf-8")
        # Path prefix keeps multi-file sets order-stable and path-sensitive.
        h.update(rel.encode("utf-8"))
        h.update(b"\0")
        h.update(body)
        h.update(b"\0")
    return h.hexdigest()


def source_paths_for(control_id: str) -> Tuple[str, ...]:
    """Per-control probe-marker path under artifacts/inventory-sources/."""
    safe = re.sub(r"[^a-zA-Z0-9._-]+", "-", str(control_id).strip()).strip("-")
    return (
        os.path.join("artifacts", "inventory-sources", "%s.probe" % safe).replace(
            "\\", "/"
        ),
    )


def write_probe_marker(
    control_id: str,
    body: bytes,
    *,
    root: Optional[Path] = None,
) -> str:
    """Write the probe-marker source file; return its relative path."""
    rel = source_paths_for(control_id)[0]
    path = containment_root(root) / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(body)
    return rel


# --------------------------------------------------------------------------
# Classification
# --------------------------------------------------------------------------


def classify_observation(obs: ProbeObservation) -> Verdict:
    """Map a probe observation to PRESENT | STUB | ABSENT.

    Binding rules:

    * handler bound + canned/seed output → **STUB** (build it)
    * handler bound + capability callable + external observable, not canned
      → **PRESENT**
    * otherwise → **ABSENT**
    """
    if obs.handler_bound and obs.returns_canned_seed:
        return Verdict.STUB
    if (
        obs.handler_bound
        and obs.capability_callable
        and obs.external_observable
        and not obs.returns_canned_seed
    ):
        return Verdict.PRESENT
    if obs.handler_bound and not obs.capability_callable:
        # Bound no-op without canned flag still counts as STUB (dead control).
        return Verdict.STUB
    return Verdict.ABSENT


def disposition_for(verdict: Verdict) -> str:
    if verdict is Verdict.PRESENT:
        return DISPOSITION_WIRE_IT
    if verdict is Verdict.STUB:
        return DISPOSITION_BUILD_IT
    return DISPOSITION_E1_CANDIDATE


# --------------------------------------------------------------------------
# Transcript helpers
# --------------------------------------------------------------------------


def transcript_relpath_for(control_id: str) -> str:
    safe = re.sub(r"[^a-zA-Z0-9._-]+", "-", control_id.strip()).strip("-")
    return os.path.join(TRANSCRIPTS_RELDIR, "%s.json" % safe).replace("\\", "/")


def write_transcript(
    control_id: str,
    *,
    observation: ProbeObservation,
    verdict: Verdict,
    root: Optional[Path] = None,
    probe_date: Optional[str] = None,
    extra: Optional[Mapping[str, Any]] = None,
) -> str:
    """Write a captured-once transcript under artifacts/transcripts/.

    Returns the relative transcript path (posix-style).
    """
    base = containment_root(root)
    rel = transcript_relpath_for(control_id)
    path = base / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    payload: Dict[str, Any] = {
        "control_id": control_id,
        "label": CONTROL_LABELS.get(control_id, control_id),
        "probe_date": probe_date or today_utc().isoformat(),
        "verdict": verdict.value,
        "handler_bound": observation.handler_bound,
        "returns_canned_seed": observation.returns_canned_seed,
        "capability_callable": observation.capability_callable,
        "external_observable": observation.external_observable,
        "output_excerpt": observation.output_excerpt,
        "notes": observation.notes,
    }
    if extra:
        payload.update(dict(extra))
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return rel.replace("\\", "/")


def load_transcript(
    transcript_path: str, *, root: Optional[Path] = None
) -> Dict[str, Any]:
    base = containment_root(root)
    rel = str(transcript_path).replace("\\", "/").lstrip("/")
    path = base / rel
    if not path.is_file():
        raise VerdictWithoutEvidence(
            "%s: %s (transcript missing: %s)"
            % (VERDICT_WITHOUT_EVIDENCE, "unknown", rel)
        )
    return json.loads(path.read_text(encoding="utf-8"))


# --------------------------------------------------------------------------
# Row construction + illegal reclassification
# --------------------------------------------------------------------------


def _require_evidence(
    control_id: str,
    transcript_path: Optional[str],
    source_hash: Optional[str],
    source_paths: Sequence[str],
) -> None:
    if not str(transcript_path or "").strip():
        raise VerdictWithoutEvidence(
            "%s: %s" % (VERDICT_WITHOUT_EVIDENCE, control_id)
        )
    if not str(source_hash or "").strip():
        raise VerdictWithoutEvidence(
            "%s: %s (missing source hash)" % (VERDICT_WITHOUT_EVIDENCE, control_id)
        )
    if not source_paths:
        raise VerdictWithoutEvidence(
            "%s: %s (missing source path list)"
            % (VERDICT_WITHOUT_EVIDENCE, control_id)
        )


def make_row(
    control_id: str,
    verdict: Union[Verdict, str],
    *,
    transcript_path: str,
    source_paths: Sequence[str],
    source_hash: str,
    probe_date: Union[str, date, datetime],
    evidence_mode: str = EVIDENCE_LIVE,
    notes: str = "",
    label: str = "",
    disposition: Optional[str] = None,
) -> InventoryRow:
    """Build a validated inventory row. Refuses verdict without evidence."""
    cid = str(control_id or "").strip()
    if not cid:
        raise InventoryError("control_id is required")
    v = parse_verdict(verdict)
    paths = tuple(str(p).replace("\\", "/") for p in source_paths)
    _require_evidence(cid, transcript_path, source_hash, paths)

    mode = str(evidence_mode or "").strip().lower()
    if mode not in {EVIDENCE_LIVE, EVIDENCE_REPLAY}:
        raise InventoryError(
            "evidence_mode must be %r or %r, got %r"
            % (EVIDENCE_LIVE, EVIDENCE_REPLAY, evidence_mode)
        )

    d = parse_probe_date(probe_date).isoformat()
    disp = disposition if disposition is not None else disposition_for(v)
    # STUB always routes to build it — disposition is not discretionary.
    if v is Verdict.STUB:
        disp = DISPOSITION_BUILD_IT
    if v is Verdict.PRESENT and disp != DISPOSITION_WIRE_IT:
        # PRESENT may only be "wire it" (E1 is illegal for PRESENT).
        disp = DISPOSITION_WIRE_IT

    return InventoryRow(
        control_id=cid,
        verdict=v,
        transcript_path=str(transcript_path).replace("\\", "/"),
        source_paths=paths,
        source_hash=str(source_hash).strip().lower(),
        probe_date=d,
        evidence_mode=mode,
        disposition=disp,
        notes=str(notes or ""),
        label=label or CONTROL_LABELS.get(cid, cid),
    )


def refuse_stub_to_absent(
    previous: Optional[Union[Verdict, str, InventoryRow]],
    new_verdict: Union[Verdict, str],
) -> None:
    """Refuse STUB → ABSENT reclassification (never auto-downgraded)."""
    if previous is None:
        return
    if isinstance(previous, InventoryRow):
        prev_v = previous.verdict
    else:
        prev_v = parse_verdict(previous)
    new_v = parse_verdict(new_verdict)
    if prev_v is Verdict.STUB and new_v is Verdict.ABSENT:
        raise IllegalReclassification(STUB_TO_ABSENT_MESSAGE)


def record_verdict(
    control_id: str,
    verdict: Union[Verdict, str],
    *,
    transcript_path: str,
    source_paths: Sequence[str],
    source_hash: str,
    probe_date: Union[str, date, datetime],
    evidence_mode: str = EVIDENCE_LIVE,
    notes: str = "",
    previous: Optional[InventoryRow] = None,
    label: str = "",
) -> InventoryRow:
    """Record a new verdict, enforcing evidence + no STUB→ABSENT downgrade."""
    refuse_stub_to_absent(previous, verdict)
    return make_row(
        control_id,
        verdict,
        transcript_path=transcript_path,
        source_paths=source_paths,
        source_hash=source_hash,
        probe_date=probe_date,
        evidence_mode=evidence_mode,
        notes=notes,
        label=label,
    )


def probe_control(
    observation: ProbeObservation,
    *,
    source_paths: Sequence[str],
    root: Optional[Path] = None,
    probe_date: Optional[Union[str, date, datetime]] = None,
    evidence_mode: str = EVIDENCE_LIVE,
    previous: Optional[InventoryRow] = None,
    content_overrides: Optional[Mapping[str, bytes]] = None,
    write_transcript_file: bool = True,
    notes: str = "",
) -> InventoryRow:
    """Classify an observation, write/read transcript, return a row.

    Idempotence: re-probing the same observation against an unchanged source
    hash returns a byte-identical verdict row (same ``canonical_bytes()``).
    """
    verdict = classify_observation(observation)
    refuse_stub_to_absent(previous, verdict)

    pd = parse_probe_date(probe_date or today_utc())
    src_hash = hash_sources(
        source_paths, root=root, content_overrides=content_overrides
    )
    rel = transcript_relpath_for(observation.control_id)

    if write_transcript_file:
        write_transcript(
            observation.control_id,
            observation=observation,
            verdict=verdict,
            root=root,
            probe_date=pd.isoformat(),
            extra={"source_hash": src_hash, "source_paths": list(source_paths)},
        )
    else:
        # Still require a transcript path that exists (evidence rule).
        base = containment_root(root)
        if not (base / rel).is_file():
            raise VerdictWithoutEvidence(
                "%s: %s" % (VERDICT_WITHOUT_EVIDENCE, observation.control_id)
            )

    return record_verdict(
        observation.control_id,
        verdict,
        transcript_path=rel,
        source_paths=source_paths,
        source_hash=src_hash,
        probe_date=pd,
        evidence_mode=evidence_mode,
        notes=notes or observation.notes,
        previous=previous,
    )


# --------------------------------------------------------------------------
# Staleness + authorization
# --------------------------------------------------------------------------


def row_age_days(row: InventoryRow, *, as_of: Optional[date] = None) -> int:
    probe = parse_probe_date(row.probe_date)
    ref = as_of if as_of is not None else today_utc()
    return (ref - probe).days


def is_stale_by_age(row: InventoryRow, *, as_of: Optional[date] = None) -> bool:
    return row_age_days(row, as_of=as_of) > STALENESS_DAYS


def is_stale_by_hash(
    row: InventoryRow,
    *,
    root: Optional[Path] = None,
    head_hash: Optional[str] = None,
    content_overrides: Optional[Mapping[str, bytes]] = None,
) -> bool:
    if head_hash is not None:
        current = str(head_hash).strip().lower()
    else:
        current = hash_sources(
            row.source_paths, root=root, content_overrides=content_overrides
        )
    return current != str(row.source_hash).strip().lower()


def resolve_row(
    row: InventoryRow,
    *,
    as_of: Optional[date] = None,
    root: Optional[Path] = None,
    head_hash: Optional[str] = None,
    content_overrides: Optional[Mapping[str, bytes]] = None,
) -> ResolvedRow:
    """Resolve a recorded row: age/hash mismatch → STALE (fail-closed UNKNOWN).

    STALE is treated as UNKNOWN, **not** as the last verdict. It may not
    authorize any live control until re-probed.
    """
    age = row_age_days(row, as_of=as_of)
    age_stale = age > STALENESS_DAYS
    hash_mismatch = is_stale_by_hash(
        row,
        root=root,
        head_hash=head_hash,
        content_overrides=content_overrides,
    )
    reasons: List[str] = []
    if age_stale:
        reasons.append(
            "probe_date %s is %d days old (bound %d)"
            % (row.probe_date, age, STALENESS_DAYS)
        )
    if hash_mismatch:
        reasons.append("source hash no longer matches HEAD")

    stale = age_stale or hash_mismatch
    if stale:
        effective = EffectiveState.STALE  # fail-closed; UNKNOWN for auth
    else:
        effective = EffectiveState[row.verdict.value]

    return ResolvedRow(
        row=row,
        effective=effective,
        age_days=age,
        hash_matches=not hash_mismatch,
        is_stale=stale,
        stale_reasons=tuple(reasons),
    )


def effective_as_unknown_when_stale(resolved: ResolvedRow) -> EffectiveState:
    """STALE fails closed: treated as UNKNOWN, not the last verdict."""
    if resolved.is_stale:
        return EffectiveState.UNKNOWN
    return resolved.effective


def may_authorize_live_control(
    row: InventoryRow,
    *,
    as_of: Optional[date] = None,
    root: Optional[Path] = None,
    head_hash: Optional[str] = None,
    content_overrides: Optional[Mapping[str, bytes]] = None,
) -> bool:
    """True only for live PRESENT inside the 14-day bound with matching hash.

    Replay-only PRESENT, STUB, ABSENT, and any STALE row all refuse.
    """
    resolved = resolve_row(
        row,
        as_of=as_of,
        root=root,
        head_hash=head_hash,
        content_overrides=content_overrides,
    )
    if resolved.is_stale:
        return False
    if row.verdict is not Verdict.PRESENT:
        return False
    if row.evidence_mode != EVIDENCE_LIVE:
        return False
    return True


def authorize_live_control_or_raise(
    row: InventoryRow,
    *,
    as_of: Optional[date] = None,
    root: Optional[Path] = None,
    head_hash: Optional[str] = None,
    content_overrides: Optional[Mapping[str, bytes]] = None,
) -> None:
    """Raise StaleInventory / InventoryError when live control is not authorized."""
    resolved = resolve_row(
        row,
        as_of=as_of,
        root=root,
        head_hash=head_hash,
        content_overrides=content_overrides,
    )
    if resolved.is_stale:
        raise StaleInventory(
            "%s: %s — %s"
            % (STALE_REPROBE_MESSAGE, row.control_id, "; ".join(resolved.stale_reasons))
        )
    if row.verdict is not Verdict.PRESENT:
        raise InventoryError(
            "live control not authorized for verdict %s on %s"
            % (row.verdict.value, row.control_id)
        )
    if row.evidence_mode != EVIDENCE_LIVE:
        raise InventoryError(REPLAY_LIVE_REFUSE_MESSAGE)


def may_authorize_documentation(
    row: InventoryRow,
    *,
    as_of: Optional[date] = None,
    root: Optional[Path] = None,
    head_hash: Optional[str] = None,
    content_overrides: Optional[Mapping[str, bytes]] = None,
) -> bool:
    """PRESENT (live or replay) may authorize documentation when not STALE."""
    resolved = resolve_row(
        row,
        as_of=as_of,
        root=root,
        head_hash=head_hash,
        content_overrides=content_overrides,
    )
    if resolved.is_stale:
        return False
    return row.verdict is Verdict.PRESENT


# --------------------------------------------------------------------------
# Inventory collection + markdown
# --------------------------------------------------------------------------


@dataclass
class CapabilityInventory:
    """In-memory inventory of control rows."""

    rows: Dict[str, InventoryRow] = field(default_factory=dict)

    def upsert(self, row: InventoryRow) -> InventoryRow:
        prev = self.rows.get(row.control_id)
        if prev is not None:
            refuse_stub_to_absent(prev, row.verdict)
        self.rows[row.control_id] = row
        return row

    def get(self, control_id: str) -> Optional[InventoryRow]:
        return self.rows.get(control_id)

    def require(self, control_id: str) -> InventoryRow:
        row = self.rows.get(control_id)
        if row is None:
            raise InventoryError("no inventory row for control %r" % control_id)
        return row

    def list_rows(self) -> List[InventoryRow]:
        order = {cid: i for i, cid in enumerate(REQUIRED_CONTROLS)}
        return sorted(
            self.rows.values(),
            key=lambda r: (order.get(r.control_id, 999), r.control_id),
        )

    def missing_required(self) -> List[str]:
        return [c for c in REQUIRED_CONTROLS if c not in self.rows]

    def gate(self) -> str:
        """Inventory gate: every required control must have evidence-backed row."""
        missing = self.missing_required()
        if missing:
            return HALT
        for row in self.rows.values():
            try:
                _require_evidence(
                    row.control_id,
                    row.transcript_path,
                    row.source_hash,
                    row.source_paths,
                )
            except VerdictWithoutEvidence:
                return HALT
        return GO


def inventory_markdown(inv: CapabilityInventory) -> str:
    """Render CAPABILITY-INVENTORY.md body."""
    lines: List[str] = [
        "# Capability Inventory",
        "",
        "Build: Anchor sleep cycle 2026-07-28 (v1.2)",
        "Wave: W3 — Phase 1: Capability Inventory harness "
        "(PRESENT / STUB / ABSENT with transcripts)",
        "",
        "## Binding rules (machine-enforced in tools/capability_inventory.py)",
        "",
        "- Verdicts: **PRESENT** | **STUB** | **ABSENT** only",
        "- **STUB is never auto-downgraded to ABSENT**",
        "- Every row requires a non-empty transcript path + SHA-256 source hash; "
        "missing either is `verdict without evidence` naming the control",
        "- Staleness bound: **%d days** — a row older than that, or whose source "
        "hash no longer matches HEAD, is **STALE**" % STALENESS_DAYS,
        "- STALE fails closed: treated as **UNKNOWN**, not the last verdict; "
        "may not authorize any live control until re-probed",
        "- Replay authority: PRESENT from replay may authorize *documentation* "
        "only; shipping a live control requires a **live** probe inside the "
        "bound against a matching source hash",
        "- STUB disposition is always **build it** (never wire it, never E1)",
        "",
        "## Controls",
        "",
        "| control | label | verdict | disposition | probe_date | evidence | "
        "source_hash | transcript | source_paths | notes |",
        "|---------|-------|---------|-------------|------------|----------|"
        "-------------|------------|--------------|-------|",
    ]
    for row in inv.list_rows():
        srcs = ", ".join(row.source_paths)
        notes = (row.notes or "").replace("|", "\\|")
        lines.append(
            "| `%s` | %s | **%s** | %s | %s | %s | `%s` | `%s` | %s | %s |"
            % (
                row.control_id,
                row.label or CONTROL_LABELS.get(row.control_id, row.control_id),
                row.verdict.value,
                row.disposition,
                row.probe_date,
                row.evidence_mode,
                row.source_hash,
                row.transcript_path,
                srcs,
                notes,
            )
        )
    lines.extend(
        [
            "",
            "## Coverage",
            "",
            "Required controls: %d" % len(REQUIRED_CONTROLS),
            "Recorded rows: %d" % len(inv.rows),
            "Missing: %s"
            % (
                ", ".join(inv.missing_required())
                if inv.missing_required()
                else "_(none)_"
            ),
            "",
        ]
    )
    return "\n".join(lines)


def write_inventory_markdown(
    inv: CapabilityInventory, *, root: Optional[Path] = None, force: bool = True
) -> Path:
    path = inventory_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and not force:
        return path
    path.write_text(inventory_markdown(inv), encoding="utf-8")
    return path


def parse_inventory_markdown(
    text: str, *, root: Optional[Path] = None
) -> CapabilityInventory:
    """Best-effort parse of CAPABILITY-INVENTORY.md table into an inventory.

    Used by surface waves / freeze gate to load the shipped artifact. Rows
    missing transcript or hash are refused when later validated. When a
    transcript JSON is present it supplies the authoritative full source_hash
    (the markdown table is the human view; the transcript is the evidence).
    """
    inv = CapabilityInventory()
    base = containment_root(root)
    for line in text.splitlines():
        line = line.strip()
        if not line.startswith("|"):
            continue
        if line.startswith("| control") or line.startswith("|---"):
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        if len(cells) < 10:
            continue
        control_raw = cells[0].strip("`").strip()
        if not control_raw or control_raw.startswith("_"):
            continue
        try:
            verdict = parse_verdict(cells[2].replace("*", "").strip())
        except InventoryError:
            continue
        transcript = cells[7].strip("`").strip()
        source_paths = tuple(
            p.strip() for p in cells[8].split(",") if p.strip()
        )
        probe_date = cells[4].strip()
        evidence = cells[5].strip()
        notes = cells[9] if len(cells) > 9 else ""
        source_hash = cells[6].strip("`").strip().rstrip("…").rstrip(".")
        # Prefer full hash + paths from the transcript JSON when present.
        if transcript:
            tpath = base / transcript.replace("\\", "/")
            if tpath.is_file():
                try:
                    data = json.loads(tpath.read_text(encoding="utf-8"))
                    if data.get("source_hash"):
                        source_hash = str(data["source_hash"]).strip().lower()
                    if data.get("source_paths"):
                        source_paths = tuple(
                            str(p).replace("\\", "/") for p in data["source_paths"]
                        )
                    if data.get("probe_date"):
                        probe_date = str(data["probe_date"])
                except (OSError, ValueError, TypeError, KeyError):
                    pass
        if not source_paths:
            source_paths = source_paths_for(control_raw)
        inv.rows[control_raw] = InventoryRow(
            control_id=control_raw,
            verdict=verdict,
            transcript_path=transcript,
            source_paths=source_paths,
            source_hash=source_hash,
            probe_date=probe_date,
            evidence_mode=evidence or EVIDENCE_LIVE,
            disposition=cells[3].strip(),
            notes=notes,
            label=cells[1].strip(),
        )
    return inv


def load_inventory(*, root: Optional[Path] = None) -> CapabilityInventory:
    path = inventory_path(root)
    if not path.is_file():
        return CapabilityInventory()
    return parse_inventory_markdown(path.read_text(encoding="utf-8"), root=root)


def load_row_from_transcript(
    control_id: str,
    *,
    root: Optional[Path] = None,
    evidence_mode: str = EVIDENCE_REPLAY,
    source_paths: Optional[Sequence[str]] = None,
) -> InventoryRow:
    """Rebuild a row by replaying a stored transcript (documentation authority)."""
    rel = transcript_relpath_for(control_id)
    data = load_transcript(rel, root=root)
    verdict = parse_verdict(data.get("verdict", "ABSENT"))
    paths = list(source_paths or data.get("source_paths") or [])
    if not paths:
        paths = ["tools/capability_inventory.py"]
    src_hash = data.get("source_hash") or hash_sources(paths, root=root)
    if not data:
        raise VerdictWithoutEvidence(
            "%s: %s" % (VERDICT_WITHOUT_EVIDENCE, control_id)
        )
    return make_row(
        control_id,
        verdict,
        transcript_path=rel,
        source_paths=paths,
        source_hash=str(src_hash),
        probe_date=str(data.get("probe_date") or today_utc().isoformat()),
        evidence_mode=evidence_mode,
        notes=str(data.get("notes") or ""),
    )


# --------------------------------------------------------------------------
# Default Phase-1 probe set (transcript-backed fixtures for this effort)
# --------------------------------------------------------------------------

#: Canned Diagnose seed string (verbatim in transcripts — STUB evidence).
DIAGNOSE_CANNED_SEED = (
    "[seed] all systems nominal (fixture) — canned Doctor diagnose output; "
    "not a live reading"
)

#: Probe-marker bodies for the Phase-1 default inventory.
#: ABSENT markers are empty bytes (content hash of empty); STUB Diagnose
#: markers carry the canned-seed line so the row is bound to that evidence.
ABSENT_PROBE_BODY = b""
STUB_DIAGNOSE_PROBE_BODY = DIAGNOSE_CANNED_SEED.encode("utf-8")


def default_probe_plan() -> List[ProbeObservation]:
    """Observations that seed the Phase-1 inventory for this effort tree.

    Honest default for a stage2 sandbox that does not yet ship product
    surfaces: Diagnose (and per-engine seats) are STUB (handler bound, canned
    seed); open/run/retry/restart/stop/preview/collapse/cadence are ABSENT
    until surface waves build them. PRESENT is reserved for live probes.
    """
    observations: List[ProbeObservation] = []

    # ABSENT controls — no handler in this effort tree yet.
    for cid in (
        "open",
        "run",
        "retry",
        "restart_run",
        "restart_session",
        "restart_engine",
        "restart_workbench",
        "stop_summary",
        "preview_path",
        "projects_collapse",
        "cadence_telemetry",
    ):
        observations.append(
            ProbeObservation(
                control_id=cid,
                handler_bound=False,
                returns_canned_seed=False,
                capability_callable=False,
                external_observable=False,
                notes="no handler bound in stage2 tree at Phase-1 inventory",
                output_excerpt="(no handler)",
            )
        )

    # STUB — Diagnose family (bound but canned seed).
    for cid in ("diagnose", "diagnose_claude", "diagnose_gemini", "diagnose_grok"):
        observations.append(
            ProbeObservation(
                control_id=cid,
                handler_bound=True,
                returns_canned_seed=True,
                capability_callable=False,
                external_observable=False,
                notes="handler bound but returns canned seed — build it",
                output_excerpt=DIAGNOSE_CANNED_SEED,
            )
        )
    return observations


def run_default_inventory(
    *,
    root: Optional[Path] = None,
    probe_date: Optional[Union[str, date]] = None,
    evidence_mode: str = EVIDENCE_LIVE,
) -> CapabilityInventory:
    """Probe every required control, write markers + transcripts, return inventory."""
    inv = CapabilityInventory()
    pd = parse_probe_date(probe_date or today_utc())
    for obs in default_probe_plan():
        if obs.returns_canned_seed:
            body = STUB_DIAGNOSE_PROBE_BODY
        else:
            body = ABSENT_PROBE_BODY
        paths = source_paths_for(obs.control_id)
        write_probe_marker(obs.control_id, body, root=root)
        row = probe_control(
            obs,
            source_paths=paths,
            root=root,
            probe_date=pd,
            evidence_mode=evidence_mode,
            write_transcript_file=True,
        )
        inv.upsert(row)
    return inv


def bootstrap_phase1(
    *,
    root: Optional[Path] = None,
    probe_date: Optional[Union[str, date]] = None,
) -> Tuple[CapabilityInventory, Path]:
    """Run default probes + write CAPABILITY-INVENTORY.md. Returns (inv, path)."""
    inv = run_default_inventory(root=root, probe_date=probe_date)
    path = write_inventory_markdown(inv, root=root, force=True)
    return inv, path


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------


def main(argv: Optional[Sequence[str]] = None) -> int:
    import sys

    args = list(sys.argv[1:] if argv is None else argv)
    if args and args[0] == "--bootstrap":
        inv, path = bootstrap_phase1()
        print("inventory:", path.as_posix())
        print("rows:", len(inv.rows))
        print("gate:", inv.gate())
        return 0 if inv.gate() == GO else 1
    if args and args[0] == "--check":
        inv = load_inventory()
        missing = inv.missing_required()
        print("rows:", len(inv.rows))
        print("missing:", missing or "(none)")
        print("gate:", inv.gate())
        return 0 if inv.gate() == GO else 1
    # Default: show rules + control list.
    print("staleness_days:", STALENESS_DAYS)
    print("required_controls:", len(REQUIRED_CONTROLS))
    for c in REQUIRED_CONTROLS:
        print(" -", c, "—", CONTROL_LABELS.get(c, c))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
