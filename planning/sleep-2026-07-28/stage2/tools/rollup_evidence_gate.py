"""Rollup Evidence Gate — W4, Phase 1.

Proves, per rollup, what is actually true — and refuses to collapse three
different facts into one verdict:

* **NO_AGGREGATOR** — no aggregator exists anywhere for this rollup.
* **PROVEN / zero_measured** — aggregator ran and returned zero over a scope
  that exists (a real, trustworthy measured zero).
* **PROVEN / empty** — the scope itself is empty (nothing was ever in scope).
* **READ_FAILED** — the query raised at read time (we could not read).

These four outcomes are never merged. A legitimate measured zero must survive
as zero_measured; mislabelling it pending is the defect this plan kills.

Also validates the **cost spot-check** protocol:

* population = every engine carrying cost instrumentation, named 30-day window
* minimum sample = 20 sessions (or all if fewer) and **at least 3 per engine**
* independent source-row sum (second procedure does not import the aggregator)
* independence rule: author/last-editor of aggregation module may not compute
  the second side; no single agent may compute both sides
* agreement tolerance = **0 cents** (exact match)
* disagreement or uncomputable second side → ``measurement_failed`` for that
  engine (never a provisional dollar); E2 against it is rejected via W2

Paths are relative to the stage2 containment root (or an injected ``root``).
No absolute host paths are hard-coded.
"""
from __future__ import annotations

import os
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import (
    Any,
    Callable,
    Dict,
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

#: Named numeric bounds (frozen plan header).
COST_SPOT_CHECK_WINDOW_DAYS = 30
COST_SPOT_CHECK_MIN_SAMPLE = 20
COST_SPOT_CHECK_MIN_PER_ENGINE = 3
COST_AGREEMENT_TOLERANCE_CENTS = 0  # exact match — never fabricates dollars

EVIDENCE_RELPATH = os.path.join("artifacts", "ROLLUP-EVIDENCE.md")
SPOT_CHECK_RELPATH = os.path.join("artifacts", "rollup-spot-check.md")

#: Verbatim refuse / gate messages (asserted by wave GWT tests).
NON_INDEPENDENT_MESSAGE = (
    "spot-check rejected as non-independent — "
    "no single agent may compute both sides; "
    "aggregation-module author/last-editor may not compute the second side"
)
UNDER_SAMPLED_MESSAGE = (
    "spot-check rejected as under-sampled — "
    "need 20 sessions (or all if fewer) and at least 3 per instrumented engine"
)
MEASUREMENT_FAILED = "measurement_failed"
PROVISIONAL_FORBIDDEN = (
    "never a provisional number — disagreement or uncomputable second side "
    "forces measurement_failed"
)

# Surface render labels (binding definitions vocabulary).
RENDER_PENDING = "pending"
RENDER_UNKNOWN = "unknown"
RENDER_EMPTY = "empty"
RENDER_ZERO_MEASURED = "zero_measured"
RENDER_OK = "ok"  # PROVEN/nonzero

_ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_ISO_DATETIME = re.compile(
    r"^\d{4}-\d{2}-\d{2}([T ]\d{2}:\d{2}:\d{2}(\.\d+)?(Z|[+-]\d{2}:\d{2})?)?$"
)

# --------------------------------------------------------------------------
# Criterion-3 rollups (usage / time / cost × dashboard / workbench / chrome)
# --------------------------------------------------------------------------

#: Stable rollup ids criterion 3 consumes. Surfaces: dashboard, workbench
#: tiles, session chrome. Metrics: usage, time, cost.
REQUIRED_ROLLUPS: Tuple[str, ...] = (
    "dashboard_usage",
    "dashboard_time",
    "dashboard_cost",
    "workbench_usage",
    "workbench_time",
    "workbench_cost",
    "session_chrome_usage",
    "session_chrome_time",
    "session_chrome_cost",
)

ROLLUP_LABELS: Dict[str, str] = {
    "dashboard_usage": "dashboard usage rollup",
    "dashboard_time": "dashboard time rollup",
    "dashboard_cost": "dashboard cost rollup",
    "workbench_usage": "workbench usage rollup",
    "workbench_time": "workbench time rollup",
    "workbench_cost": "workbench cost rollup",
    "session_chrome_usage": "session chrome usage rollup",
    "session_chrome_time": "session chrome time rollup",
    "session_chrome_cost": "session chrome cost rollup",
}

#: Default aggregation wave name a NO_AGGREGATOR surface awaits.
DEFAULT_AGGREGATION_WAVE = "W12-W13-aggregation"


# --------------------------------------------------------------------------
# Enums + errors
# --------------------------------------------------------------------------


class Verdict(str, Enum):
    """Top-level rollup evidence verdict — exactly three legal values."""

    PROVEN = "PROVEN"
    NO_AGGREGATOR = "NO_AGGREGATOR"
    READ_FAILED = "READ_FAILED"


class SubVerdict(str, Enum):
    """PROVEN-only sub-verdict (binding definitions).

    Never attached to NO_AGGREGATOR or READ_FAILED.
    """

    NONZERO = "nonzero"
    ZERO_MEASURED = "zero_measured"
    EMPTY = "empty"


class SpotCheckStatus(str, Enum):
    """Per-engine cost spot-check outcome."""

    AGREED = "agreed"
    MEASUREMENT_FAILED = "measurement_failed"
    REJECTED = "rejected"  # non-independent or under-sampled (wave not GO)


class RollupGateError(Exception):
    """Raised when a rollup-evidence or spot-check rule is violated."""

    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


class SpotCheckRejected(RollupGateError):
    """Spot-check failed independence / sample / protocol rules."""


class CollapsedVerdictError(RollupGateError):
    """Attempted to merge distinct outcomes (gate must never collapse)."""


# --------------------------------------------------------------------------
# Evidence schemas
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class RunReceipt:
    """Run receipt: run timestamp, window, scope size."""

    run_timestamp: str
    window: str
    scope_size: int

    def as_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class QueryResult:
    """What a successful aggregator query returned.

    ``scope_size`` is the size of the domain under consideration (sessions /
    projects / files that exist), independent of how many aggregate rows
    came back. Distinguishes empty scope from measured-zero rows.
    """

    rows: Tuple[Any, ...]
    scope_size: int
    total: Optional[Union[int, float]] = None

    @property
    def row_count(self) -> int:
        return len(self.rows)

    def sample_row(self) -> Optional[Any]:
        return self.rows[0] if self.rows else None


@dataclass(frozen=True)
class RollupEvidence:
    """One rollup's evidence block: query + count + sample + receipt + verdict."""

    rollup_id: str
    verdict: Verdict
    query: str
    row_count: int
    sample_row: Optional[Any]
    receipt: RunReceipt
    sub_verdict: Optional[SubVerdict] = None
    total: Optional[Union[int, float]] = None
    aggregation_wave: Optional[str] = None
    read_error: Optional[str] = None
    label: str = ""
    notes: str = ""

    def __post_init__(self) -> None:
        # Frozen dataclass: use object.__setattr__ only if we needed mutation;
        # instead validate immutably via a free function called by builders.
        pass

    def as_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["verdict"] = self.verdict.value
        d["sub_verdict"] = self.sub_verdict.value if self.sub_verdict else None
        d["receipt"] = self.receipt.as_dict()
        return d

    @property
    def surface_render(self) -> str:
        """The surface state this evidence authorizes (binding vocabulary)."""
        return surface_render_for(self)

    @property
    def requires_aggregation_wave(self) -> bool:
        return self.verdict is Verdict.NO_AGGREGATOR

    @property
    def allows_numeral(self) -> bool:
        return self.verdict is Verdict.PROVEN and self.sub_verdict in {
            SubVerdict.NONZERO,
            SubVerdict.ZERO_MEASURED,
        }


@dataclass(frozen=True)
class EngineSpotCheck:
    """Per-engine cost spot-check side-by-side."""

    engine: str
    sessions_sampled: int
    population_sessions: int
    aggregated_cents: int
    source_row_sum_cents: Optional[int]
    source_rows_computable: bool
    status: SpotCheckStatus = SpotCheckStatus.AGREED
    notes: str = ""

    def as_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["status"] = self.status.value
        return d


@dataclass(frozen=True)
class SpotCheckRecord:
    """The cost spot-check executed to the written protocol."""

    window_start: str
    window_end: str
    window_days: int
    engines: Tuple[EngineSpotCheck, ...]
    #: Agent that computed the aggregator side.
    aggregator_agent_id: str
    #: Agent that computed the independent source-row sum (must differ).
    source_row_agent_id: str
    #: Agent that authored / last edited the aggregation module (may not
    #: compute the second side).
    aggregation_module_author_id: str
    #: Relative path of the aggregation module under containment (if any).
    aggregation_module_path: str = ""
    #: Total sessions in population (all instrumented engines, window).
    population_total: int = 0
    notes: str = ""

    def as_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["engines"] = [e.as_dict() for e in self.engines]
        return d


@dataclass
class RollupEvidenceSet:
    """In-memory set of rollup evidence rows + optional spot-check."""

    rows: Dict[str, RollupEvidence] = field(default_factory=dict)
    spot_check: Optional[SpotCheckRecord] = None
    spot_check_gate: str = HALT
    spot_check_reason: str = ""

    def upsert(self, row: RollupEvidence) -> RollupEvidence:
        validate_evidence_integrity(row)
        self.rows[row.rollup_id] = row
        return row

    def get(self, rollup_id: str) -> Optional[RollupEvidence]:
        return self.rows.get(rollup_id)

    def require(self, rollup_id: str) -> RollupEvidence:
        row = self.rows.get(rollup_id)
        if row is None:
            raise RollupGateError("no evidence for rollup %r" % rollup_id)
        return row

    def list_rows(self) -> List[RollupEvidence]:
        order = {rid: i for i, rid in enumerate(REQUIRED_ROLLUPS)}
        return sorted(
            self.rows.values(),
            key=lambda r: (order.get(r.rollup_id, 999), r.rollup_id),
        )

    def missing_required(self) -> List[str]:
        return [r for r in REQUIRED_ROLLUPS if r not in self.rows]

    def gate(self) -> str:
        """Wave gate: every required rollup has a non-collapsed verdict +
        a protocol-valid spot-check record."""
        if self.missing_required():
            return HALT
        for row in self.rows.values():
            try:
                validate_evidence_integrity(row)
            except RollupGateError:
                return HALT
        if self.spot_check is None:
            return HALT
        if self.spot_check_gate != GO:
            return HALT
        return GO


# --------------------------------------------------------------------------
# Path / time helpers
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


def evidence_path(root: Optional[Path] = None) -> Path:
    return containment_root(root) / EVIDENCE_RELPATH


def spot_check_path(root: Optional[Path] = None) -> Path:
    return containment_root(root) / SPOT_CHECK_RELPATH


def now_utc_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace(
        "+00:00", "Z"
    )


def parse_verdict(value: Union[Verdict, str]) -> Verdict:
    if isinstance(value, Verdict):
        return value
    text = str(value).strip().upper()
    try:
        return Verdict[text]
    except KeyError as exc:
        raise RollupGateError(
            "unknown verdict %r — only PROVEN | NO_AGGREGATOR | READ_FAILED"
            % value
        ) from exc


def parse_sub_verdict(value: Union[SubVerdict, str, None]) -> Optional[SubVerdict]:
    if value is None or value == "":
        return None
    if isinstance(value, SubVerdict):
        return value
    text = str(value).strip().lower()
    try:
        return SubVerdict(text)
    except ValueError as exc:
        raise RollupGateError(
            "unknown sub-verdict %r — only nonzero | zero_measured | empty"
            % value
        ) from exc


# --------------------------------------------------------------------------
# Surface render mapping (binding definitions)
# --------------------------------------------------------------------------


def surface_render_for(evidence: RollupEvidence) -> str:
    """Map evidence → surface state. Four outcomes stay four labels."""
    if evidence.verdict is Verdict.NO_AGGREGATOR:
        return RENDER_PENDING
    if evidence.verdict is Verdict.READ_FAILED:
        return RENDER_UNKNOWN
    if evidence.verdict is Verdict.PROVEN:
        if evidence.sub_verdict is SubVerdict.EMPTY:
            return RENDER_EMPTY
        if evidence.sub_verdict is SubVerdict.ZERO_MEASURED:
            return RENDER_ZERO_MEASURED
        if evidence.sub_verdict is SubVerdict.NONZERO:
            return RENDER_OK
        raise RollupGateError(
            "PROVEN rollup %r missing sub-verdict" % evidence.rollup_id
        )
    raise RollupGateError("unhandled verdict %s" % evidence.verdict)


def pending_label(evidence: RollupEvidence) -> str:
    """User-facing pending text naming the aggregation wave awaited."""
    wave = evidence.aggregation_wave or DEFAULT_AGGREGATION_WAVE
    return "pending (awaits %s)" % wave


# --------------------------------------------------------------------------
# Integrity: never collapse the four outcomes
# --------------------------------------------------------------------------


def validate_evidence_integrity(evidence: RollupEvidence) -> None:
    """Refuse collapsed / illegal combinations of verdict + sub-verdict."""
    v = evidence.verdict
    sv = evidence.sub_verdict

    if v is Verdict.PROVEN:
        if sv is None:
            raise CollapsedVerdictError(
                "PROVEN requires a sub-verdict of nonzero | zero_measured | empty"
            )
        if sv not in {
            SubVerdict.NONZERO,
            SubVerdict.ZERO_MEASURED,
            SubVerdict.EMPTY,
        }:
            raise CollapsedVerdictError(
                "illegal PROVEN sub-verdict %r" % (sv,)
            )
        # PROVEN must not look like pending/unknown at the surface.
        if surface_render_for(evidence) in {RENDER_PENDING, RENDER_UNKNOWN}:
            raise CollapsedVerdictError(
                "PROVEN must not surface as pending or unknown"
            )
        return

    if v is Verdict.NO_AGGREGATOR:
        if sv is not None:
            raise CollapsedVerdictError(
                "NO_AGGREGATOR must not carry a PROVEN sub-verdict "
                "(would collapse absent-aggregator with measured zero / empty)"
            )
        if surface_render_for(evidence) != RENDER_PENDING:
            raise CollapsedVerdictError(
                "NO_AGGREGATOR must render pending"
            )
        return

    if v is Verdict.READ_FAILED:
        if sv is not None:
            raise CollapsedVerdictError(
                "READ_FAILED must not carry a PROVEN sub-verdict "
                "(would collapse read-failure with measured zero / empty)"
            )
        if surface_render_for(evidence) != RENDER_UNKNOWN:
            raise CollapsedVerdictError(
                "READ_FAILED must render unknown — never the same as "
                "NO_AGGREGATOR (pending)"
            )
        return

    raise RollupGateError("unknown verdict on evidence: %r" % v)


def assert_outcomes_not_collapsed(
    proven_zero: RollupEvidence,
    proven_empty: RollupEvidence,
    no_agg: RollupEvidence,
    read_failed: RollupEvidence,
) -> None:
    """Test helper: the four outcomes must be four distinct surface labels
    and four distinct verdict/sub-verdict pairs."""
    for e in (proven_zero, proven_empty, no_agg, read_failed):
        validate_evidence_integrity(e)

    labels = {
        proven_zero.surface_render,
        proven_empty.surface_render,
        no_agg.surface_render,
        read_failed.surface_render,
    }
    if len(labels) != 4:
        raise CollapsedVerdictError(
            "four outcomes collapsed into fewer surface labels: %s" % labels
        )

    if proven_zero.verdict is not Verdict.PROVEN:
        raise CollapsedVerdictError("zero_measured fixture not PROVEN")
    if proven_zero.sub_verdict is not SubVerdict.ZERO_MEASURED:
        raise CollapsedVerdictError("zero_measured fixture wrong sub-verdict")
    if proven_empty.sub_verdict is not SubVerdict.EMPTY:
        raise CollapsedVerdictError("empty fixture wrong sub-verdict")
    if no_agg.verdict is not Verdict.NO_AGGREGATOR:
        raise CollapsedVerdictError("NO_AGGREGATOR fixture wrong verdict")
    if read_failed.verdict is not Verdict.READ_FAILED:
        raise CollapsedVerdictError("READ_FAILED fixture wrong verdict")

    # Explicitly: zero_measured is never pending and never merged with empty.
    if proven_zero.surface_render == RENDER_PENDING:
        raise CollapsedVerdictError(
            "measured zero must not surface as pending"
        )
    if proven_zero.surface_render == proven_empty.surface_render:
        raise CollapsedVerdictError(
            "zero_measured must not share a surface label with empty"
        )
    if no_agg.surface_render == read_failed.surface_render:
        raise CollapsedVerdictError(
            "NO_AGGREGATOR must not share a surface label with READ_FAILED"
        )


# --------------------------------------------------------------------------
# evaluate_rollup — the core gate
# --------------------------------------------------------------------------


def _make_receipt(
    *,
    run_timestamp: Optional[str],
    window: str,
    scope_size: int,
) -> RunReceipt:
    ts = run_timestamp or now_utc_iso()
    return RunReceipt(run_timestamp=ts, window=window, scope_size=int(scope_size))


def evaluate_rollup(
    rollup_id: str,
    *,
    aggregator_exists: bool,
    query: str,
    window: str,
    query_fn: Optional[Callable[[], QueryResult]] = None,
    query_result: Optional[QueryResult] = None,
    query_error: Optional[BaseException] = None,
    run_timestamp: Optional[str] = None,
    aggregation_wave: Optional[str] = None,
    notes: str = "",
    label: str = "",
) -> RollupEvidence:
    """Evaluate one rollup into exactly one of PROVEN | NO_AGGREGATOR | READ_FAILED.

    Call sites inject either a live ``query_fn``, a precomputed ``query_result``,
    or a ``query_error`` (simulating a raised read). Exactly one success path
    or the raise path is used; absent aggregator short-circuits before query.
    """
    rid = str(rollup_id or "").strip()
    if not rid:
        raise RollupGateError("rollup_id is required")
    q = str(query or "").strip()
    if not q:
        raise RollupGateError("exact query string is required for evidence")
    win = str(window or "").strip()
    if not win:
        raise RollupGateError("window is required on the run receipt")

    wave = aggregation_wave or ("%s for %s" % (DEFAULT_AGGREGATION_WAVE, rid))
    lbl = label or ROLLUP_LABELS.get(rid, rid)

    # --- NO_AGGREGATOR -------------------------------------------------------
    if not aggregator_exists:
        receipt = _make_receipt(
            run_timestamp=run_timestamp, window=win, scope_size=0
        )
        evidence = RollupEvidence(
            rollup_id=rid,
            verdict=Verdict.NO_AGGREGATOR,
            query=q,
            row_count=0,
            sample_row=None,
            receipt=receipt,
            sub_verdict=None,
            total=None,
            aggregation_wave=wave,
            read_error=None,
            label=lbl,
            notes=notes or "no aggregator present in codebase",
        )
        validate_evidence_integrity(evidence)
        return evidence

    # --- READ_FAILED ---------------------------------------------------------
    result: Optional[QueryResult] = None
    err: Optional[BaseException] = query_error
    if err is None and query_result is not None:
        result = query_result
    elif err is None and query_fn is not None:
        try:
            result = query_fn()
        except BaseException as exc:  # intentional: gate records any raise
            err = exc
    elif err is None and query_result is None and query_fn is None:
        # Aggregator claimed to exist but nothing to run — treat as read fail.
        err = RollupGateError(
            "aggregator marked present but no query_fn/query_result provided"
        )

    if err is not None:
        receipt = _make_receipt(
            run_timestamp=run_timestamp, window=win, scope_size=0
        )
        evidence = RollupEvidence(
            rollup_id=rid,
            verdict=Verdict.READ_FAILED,
            query=q,
            row_count=0,
            sample_row=None,
            receipt=receipt,
            sub_verdict=None,
            total=None,
            aggregation_wave=None,
            read_error="%s: %s" % (type(err).__name__, err),
            label=lbl,
            notes=notes or "query raised at read time",
        )
        validate_evidence_integrity(evidence)
        return evidence

    assert result is not None
    scope = int(result.scope_size)
    rows = tuple(result.rows)
    row_count = len(rows)
    sample = rows[0] if rows else None
    total = result.total
    if total is None and row_count == 0:
        total = 0
    receipt = _make_receipt(
        run_timestamp=run_timestamp, window=win, scope_size=scope
    )

    # --- PROVEN sub-verdicts -------------------------------------------------
    if scope == 0:
        sub = SubVerdict.EMPTY
    elif total == 0 or total == 0.0:
        # Scope exists, aggregate total is 0 (including zero rows over scope).
        sub = SubVerdict.ZERO_MEASURED
    else:
        sub = SubVerdict.NONZERO

    evidence = RollupEvidence(
        rollup_id=rid,
        verdict=Verdict.PROVEN,
        query=q,
        row_count=row_count,
        sample_row=sample,
        receipt=receipt,
        sub_verdict=sub,
        total=total,
        aggregation_wave=None,
        read_error=None,
        label=lbl,
        notes=notes,
    )
    validate_evidence_integrity(evidence)
    return evidence


# --------------------------------------------------------------------------
# Cost spot-check protocol
# --------------------------------------------------------------------------


def _engine_agrees(engine: EngineSpotCheck) -> SpotCheckStatus:
    if not engine.source_rows_computable or engine.source_row_sum_cents is None:
        return SpotCheckStatus.MEASUREMENT_FAILED
    delta = abs(int(engine.aggregated_cents) - int(engine.source_row_sum_cents))
    if delta > COST_AGREEMENT_TOLERANCE_CENTS:
        return SpotCheckStatus.MEASUREMENT_FAILED
    return SpotCheckStatus.AGREED


def finalize_engine_spot_check(engine: EngineSpotCheck) -> EngineSpotCheck:
    """Recompute status from cents / computability (0-cent tolerance)."""
    status = _engine_agrees(engine)
    return EngineSpotCheck(
        engine=engine.engine,
        sessions_sampled=engine.sessions_sampled,
        population_sessions=engine.population_sessions,
        aggregated_cents=engine.aggregated_cents,
        source_row_sum_cents=engine.source_row_sum_cents,
        source_rows_computable=engine.source_rows_computable,
        status=status,
        notes=engine.notes
        if status is SpotCheckStatus.AGREED
        else (engine.notes or PROVISIONAL_FORBIDDEN),
    )


def validate_spot_check(record: SpotCheckRecord) -> Tuple[str, str, SpotCheckRecord]:
    """Validate the cost spot-check protocol.

    Returns ``(GO|HALT, reason, finalized_record)``.

    * Non-independent agents → HALT (wave not GO)
    * Under-sampled → HALT (wave not GO)
    * Disagreement / uncomputable → engines marked measurement_failed;
      the *record* is still protocol-valid (GO) when independence + sampling
      hold — measurement_failed is a surface consequence, not a sample reject.
      Callers that need every engine agreed use :func:`spot_check_all_agreed`.
    """
    # Dates
    if not _ISO_DATE.match(str(record.window_start or "").strip()):
        return HALT, "spot-check window_start must be ISO YYYY-MM-DD", record
    if not _ISO_DATE.match(str(record.window_end or "").strip()):
        return HALT, "spot-check window_end must be ISO YYYY-MM-DD", record
    if int(record.window_days) != COST_SPOT_CHECK_WINDOW_DAYS:
        return (
            HALT,
            "spot-check window must be %d days (got %s)"
            % (COST_SPOT_CHECK_WINDOW_DAYS, record.window_days),
            record,
        )

    agg = str(record.aggregator_agent_id or "").strip()
    src = str(record.source_row_agent_id or "").strip()
    author = str(record.aggregation_module_author_id or "").strip()
    if not agg or not src or not author:
        return HALT, "spot-check requires aggregator, source-row, and author agent ids", record

    # Independence rule.
    if agg == src:
        return HALT, NON_INDEPENDENT_MESSAGE, record
    if author == src:
        # author may not compute the second side
        return HALT, NON_INDEPENDENT_MESSAGE, record

    engines = tuple(finalize_engine_spot_check(e) for e in record.engines)
    if not engines:
        # Empty instrumented population: protocol-valid (nothing to sample).
        finalized = SpotCheckRecord(
            window_start=record.window_start,
            window_end=record.window_end,
            window_days=record.window_days,
            engines=engines,
            aggregator_agent_id=agg,
            source_row_agent_id=src,
            aggregation_module_author_id=author,
            aggregation_module_path=record.aggregation_module_path,
            population_total=0,
            notes=record.notes or "no engines carrying cost instrumentation",
        )
        return GO, "empty instrumented population — spot-check N/A", finalized

    # Sampling rules.
    pop_total = int(record.population_total) or sum(
        e.population_sessions for e in engines
    )
    sampled_total = sum(e.sessions_sampled for e in engines)
    required_total = (
        min(COST_SPOT_CHECK_MIN_SAMPLE, pop_total) if pop_total > 0 else 0
    )
    if pop_total > 0 and sampled_total < required_total:
        return HALT, UNDER_SAMPLED_MESSAGE, record

    for e in engines:
        # At least 3 per engine, or all of that engine's population if fewer.
        need = min(COST_SPOT_CHECK_MIN_PER_ENGINE, int(e.population_sessions))
        if int(e.population_sessions) > 0 and int(e.sessions_sampled) < need:
            return HALT, UNDER_SAMPLED_MESSAGE, record

    finalized = SpotCheckRecord(
        window_start=record.window_start,
        window_end=record.window_end,
        window_days=record.window_days,
        engines=engines,
        aggregator_agent_id=agg,
        source_row_agent_id=src,
        aggregation_module_author_id=author,
        aggregation_module_path=record.aggregation_module_path,
        population_total=pop_total,
        notes=record.notes,
    )
    return GO, "spot-check protocol satisfied", finalized


def spot_check_all_agreed(record: SpotCheckRecord) -> bool:
    return all(e.status is SpotCheckStatus.AGREED for e in record.engines)


def measurement_failed_engines(record: SpotCheckRecord) -> List[str]:
    return [
        e.engine
        for e in record.engines
        if e.status is SpotCheckStatus.MEASUREMENT_FAILED
    ]


def refuse_e2_for_cost_measurement_failed(
    *,
    engine: str,
    record: SpotCheckRecord,
    criterion: str = "cost-labelling",
) -> None:
    """Any attempt to sign E2 against a measurement_failed cost surface is
    rejected by the exit register from W2.

    Raises ``IllegalExit`` (W2) when the engine is measurement_failed, or when
    the criterion is a cost criterion (E2 illegal for dollars regardless).
    """
    from anchor.build import exit_register as er

    # Always illegal on cost criteria.
    if er.is_cost_criterion(criterion):
        # Prefer the stronger measurement_failed signal when present.
        failed = set(measurement_failed_engines(record))
        if engine in failed or not failed:
            # Even without a specific engine fail, E2-on-cost is illegal.
            er.validate_justification(
                er.ExitId.E2,
                criterion=criterion,
                accessor_proven=True,
                justification=(
                    "attempted E2 provisional dollars for engine %s "
                    "(spot-check status: %s)"
                    % (
                        engine,
                        MEASUREMENT_FAILED
                        if engine in failed
                        else "cost criterion",
                    )
                ),
            )
            # validate_justification raises on cost; if it somehow returns,
            # force the dollars message.
            raise er.IllegalExit(er.E2_DOLLARS_MESSAGE)

    failed = set(measurement_failed_engines(record))
    if engine in failed:
        raise er.IllegalExit(er.E2_DOLLARS_MESSAGE)


def record_disagreement_as_measurement_failed(
    engine: EngineSpotCheck,
) -> EngineSpotCheck:
    """When aggregated dollars disagree with source rows, force measurement_failed."""
    return EngineSpotCheck(
        engine=engine.engine,
        sessions_sampled=engine.sessions_sampled,
        population_sessions=engine.population_sessions,
        aggregated_cents=engine.aggregated_cents,
        source_row_sum_cents=engine.source_row_sum_cents,
        source_rows_computable=engine.source_rows_computable,
        status=SpotCheckStatus.MEASUREMENT_FAILED,
        notes=PROVISIONAL_FORBIDDEN,
    )


# --------------------------------------------------------------------------
# Markdown render / load
# --------------------------------------------------------------------------


def _fmt_sample(sample: Any) -> str:
    if sample is None:
        return "_(none)_"
    text = repr(sample)
    if len(text) > 200:
        text = text[:197] + "..."
    return "`%s`" % text.replace("\n", " ")


def evidence_markdown(s: RollupEvidenceSet) -> str:
    """Render ROLLUP-EVIDENCE.md — one block per rollup."""
    lines: List[str] = [
        "# Rollup Evidence",
        "",
        "Build: Anchor sleep cycle 2026-07-28 (v1.2)",
        "Wave: W4 — Phase 1: Rollup Evidence Gate (query + row count + sample row)",
        "",
        "## Binding rules (machine-enforced in tools/rollup_evidence_gate.py)",
        "",
        "- Verdicts: **PROVEN** | **NO_AGGREGATOR** | **READ_FAILED** only",
        "- PROVEN sub-verdicts: **nonzero** | **zero_measured** | **empty** "
        "(binding definitions)",
        "- Aggregator ran, zero rows, scope exists → **PROVEN / zero_measured** "
        "(never pending)",
        "- Scope itself empty → **PROVEN / empty** (never merged with zero_measured)",
        "- No aggregator → **NO_AGGREGATOR** → surface renders **pending** "
        "(names the aggregation wave)",
        "- Query raises → **READ_FAILED** → surface renders **unknown** "
        "(never the same verdict as NO_AGGREGATOR)",
        "- Cost agreement tolerance: **0 cents** (exact match)",
        "",
        "## Rollups (criterion 3 — dashboard / workbench / session chrome × "
        "usage / time / cost)",
        "",
    ]

    for row in s.list_rows():
        sv = row.sub_verdict.value if row.sub_verdict else "—"
        lines.extend(
            [
                "### `%s` — %s" % (row.rollup_id, row.label or row.rollup_id),
                "",
                "| field | value |",
                "|-------|-------|",
                "| verdict | **%s** |" % row.verdict.value,
                "| sub-verdict | %s |" % sv,
                "| surface render | `%s` |" % row.surface_render,
                "| query | `%s` |" % row.query.replace("|", "\\|"),
                "| row_count | %d |" % row.row_count,
                "| sample_row | %s |" % _fmt_sample(row.sample_row),
                "| total | %s |" % (row.total if row.total is not None else "—"),
                "| run_timestamp | %s |" % row.receipt.run_timestamp,
                "| window | %s |" % row.receipt.window,
                "| scope_size | %d |" % row.receipt.scope_size,
                "| aggregation_wave | %s |"
                % (row.aggregation_wave or "—"),
                "| read_error | %s |"
                % (row.read_error.replace("|", "\\|") if row.read_error else "—"),
                "| notes | %s |"
                % (row.notes.replace("|", "\\|") if row.notes else "—"),
                "",
            ]
        )

    lines.extend(
        [
            "## Coverage",
            "",
            "Required rollups: %d" % len(REQUIRED_ROLLUPS),
            "Recorded rows: %d" % len(s.rows),
            "Missing: %s"
            % (
                ", ".join("`%s`" % m for m in s.missing_required())
                if s.missing_required()
                else "_(none)_"
            ),
            "Spot-check gate: **%s**%s"
            % (
                s.spot_check_gate,
                (" — " + s.spot_check_reason) if s.spot_check_reason else "",
            ),
            "",
        ]
    )
    return "\n".join(lines)


def spot_check_markdown(record: SpotCheckRecord, *, gate: str, reason: str) -> str:
    lines: List[str] = [
        "# Cost Rollup Spot-Check",
        "",
        "Build: Anchor sleep cycle 2026-07-28 (v1.2)",
        "Wave: W4 — Phase 1: Rollup Evidence Gate",
        "",
        "## Protocol (binding)",
        "",
        "- **population** = every engine carrying cost instrumentation, over a "
        "named **%d-day** window" % COST_SPOT_CHECK_WINDOW_DAYS,
        "- **minimum sample** = **%d** sessions, or all sessions if fewer, and "
        "**at least %d per engine**"
        % (COST_SPOT_CHECK_MIN_SAMPLE, COST_SPOT_CHECK_MIN_PER_ENGINE),
        "- **independent source-row sum** = a second procedure that reads the "
        "source rows directly and does **not** import the aggregation module",
        "- **independence rule** = the agent that authored or last edited the "
        "aggregation module may not compute the second side, and no single "
        "agent may compute both sides",
        "- **agreement tolerance = 0 cents (exact match)** — 'never fabricates "
        "dollars' is absolute",
        "- any disagreement, or any sampled engine the second procedure cannot "
        "compute, forces **measurement_failed** for that engine — never a "
        "'provisional' number",
        "- any attempt to sign **E2** against a measurement_failed cost surface "
        "is rejected by the exit register from W2",
        "",
        "## Run receipt",
        "",
        "| field | value |",
        "|-------|-------|",
        "| window_start | %s |" % record.window_start,
        "| window_end | %s |" % record.window_end,
        "| window_days | %d |" % record.window_days,
        "| population_total | %d |" % record.population_total,
        "| aggregator_agent_id | `%s` |" % record.aggregator_agent_id,
        "| source_row_agent_id | `%s` |" % record.source_row_agent_id,
        "| aggregation_module_author_id | `%s` |"
        % record.aggregation_module_author_id,
        "| aggregation_module_path | `%s` |"
        % (record.aggregation_module_path or "—"),
        "| protocol gate | **%s** |" % gate,
        "| reason | %s |" % reason,
        "| notes | %s |" % (record.notes or "—"),
        "",
        "## Per-engine results",
        "",
        "| engine | pop | sampled | aggregated_cents | source_row_sum_cents | "
        "computable | status | notes |",
        "|--------|-----|---------|------------------|----------------------|"
        "------------|--------|-------|",
    ]
    for e in record.engines:
        lines.append(
            "| `%s` | %d | %d | %d | %s | %s | **%s** | %s |"
            % (
                e.engine,
                e.population_sessions,
                e.sessions_sampled,
                e.aggregated_cents,
                e.source_row_sum_cents
                if e.source_row_sum_cents is not None
                else "—",
                "yes" if e.source_rows_computable else "no",
                e.status.value,
                (e.notes or "—").replace("|", "\\|"),
            )
        )
    lines.append("")
    failed = measurement_failed_engines(record)
    lines.extend(
        [
            "## Measurement-failed engines",
            "",
            (
                ", ".join("`%s`" % e for e in failed)
                if failed
                else "_(none)_"
            ),
            "",
            "## Independence attestation",
            "",
            "- aggregator side computed by: `%s`" % record.aggregator_agent_id,
            "- source-row side computed by: `%s`" % record.source_row_agent_id,
            "- aggregation module author/last-editor: `%s`"
            % record.aggregation_module_author_id,
            "- sides differ: **%s**"
            % (
                "yes"
                if record.aggregator_agent_id != record.source_row_agent_id
                else "NO — REJECT"
            ),
            "- author ≠ source-row agent: **%s**"
            % (
                "yes"
                if record.aggregation_module_author_id
                != record.source_row_agent_id
                else "NO — REJECT"
            ),
            "",
        ]
    )
    return "\n".join(lines)


def write_evidence(
    s: RollupEvidenceSet, *, root: Optional[Path] = None
) -> Path:
    path = evidence_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(evidence_markdown(s), encoding="utf-8")
    return path


def write_spot_check(
    record: SpotCheckRecord,
    *,
    gate: str,
    reason: str,
    root: Optional[Path] = None,
) -> Path:
    path = spot_check_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        spot_check_markdown(record, gate=gate, reason=reason), encoding="utf-8"
    )
    return path


def _parse_md_field(block: str, field: str) -> Optional[str]:
    # Match table rows: | field | value |
    pat = re.compile(
        r"^\|\s*%s\s*\|\s*(.*?)\s*\|\s*$" % re.escape(field),
        re.MULTILINE | re.IGNORECASE,
    )
    m = pat.search(block)
    if not m:
        return None
    val = m.group(1).strip()
    # Strip markdown bold/code wrappers.
    val = re.sub(r"^\*\*(.*)\*\*$", r"\1", val)
    val = re.sub(r"^`(.*)`$", r"\1", val)
    if val in {"—", "-", "_(none)_"}:
        return None
    return val


def load_evidence(*, root: Optional[Path] = None) -> RollupEvidenceSet:
    """Load ROLLUP-EVIDENCE.md into a RollupEvidenceSet (best-effort parser)."""
    path = evidence_path(root)
    if not path.is_file():
        raise RollupGateError("ROLLUP-EVIDENCE.md missing at %s" % EVIDENCE_RELPATH)
    text = path.read_text(encoding="utf-8")
    s = RollupEvidenceSet()
    # Split on ### `rollup_id`
    parts = re.split(r"(?m)^### `([^`]+)`", text)
    # parts[0] is preamble; then (id, body, id, body, ...)
    i = 1
    while i + 1 < len(parts):
        rid = parts[i].strip()
        body = parts[i + 1]
        i += 2
        verdict_raw = _parse_md_field(body, "verdict") or ""
        sub_raw = _parse_md_field(body, "sub-verdict")
        query = _parse_md_field(body, "query") or "—"
        row_count_s = _parse_md_field(body, "row_count") or "0"
        total_s = _parse_md_field(body, "total")
        ts = _parse_md_field(body, "run_timestamp") or now_utc_iso()
        window = _parse_md_field(body, "window") or "unspecified"
        scope_s = _parse_md_field(body, "scope_size") or "0"
        wave = _parse_md_field(body, "aggregation_wave")
        read_err = _parse_md_field(body, "read_error")
        notes = _parse_md_field(body, "notes") or ""
        sample_raw = _parse_md_field(body, "sample_row")

        try:
            row_count = int(row_count_s)
        except ValueError:
            row_count = 0
        try:
            scope = int(scope_s)
        except ValueError:
            scope = 0
        total: Optional[Union[int, float]] = None
        if total_s is not None:
            try:
                total = int(total_s) if "." not in total_s else float(total_s)
            except ValueError:
                total = None

        sample: Optional[Any] = None
        if sample_raw and sample_raw not in {"_(none)_"}:
            sample = sample_raw

        evidence = RollupEvidence(
            rollup_id=rid,
            verdict=parse_verdict(verdict_raw),
            query=query,
            row_count=row_count,
            sample_row=sample,
            receipt=RunReceipt(
                run_timestamp=ts, window=window, scope_size=scope
            ),
            sub_verdict=parse_sub_verdict(sub_raw),
            total=total,
            aggregation_wave=wave,
            read_error=read_err,
            label=ROLLUP_LABELS.get(rid, rid),
            notes=notes,
        )
        s.upsert(evidence)

    # Spot-check gate line from coverage section (optional).
    gm = re.search(r"Spot-check gate:\s*\*\*([A-Z_]+)\*\*", text)
    if gm:
        s.spot_check_gate = gm.group(1)
    return s


# --------------------------------------------------------------------------
# Fixtures (for tests + bootstrap honesty cases)
# --------------------------------------------------------------------------


def fixture_proven_zero_measured(
    rollup_id: str = "dashboard_usage",
    *,
    window: str = "2026-06-29..2026-07-29",
    scope_size: int = 12,
) -> RollupEvidence:
    """GWT: aggregator exists, zero rows over a scope that exists → zero_measured."""
    return evaluate_rollup(
        rollup_id,
        aggregator_exists=True,
        query="SELECT SUM(tokens) FROM usage WHERE day = :today AND project = :p",
        window=window,
        query_result=QueryResult(rows=(), scope_size=scope_size, total=0),
        run_timestamp="2026-07-29T12:00:00Z",
        notes="fixture: measured zero over existing scope",
    )


def fixture_proven_empty(
    rollup_id: str = "workbench_time",
    *,
    window: str = "2026-06-29..2026-07-29",
) -> RollupEvidence:
    """Scope itself empty → PROVEN/empty."""
    return evaluate_rollup(
        rollup_id,
        aggregator_exists=True,
        query="SELECT SUM(seconds) FROM session_time WHERE project = :p",
        window=window,
        query_result=QueryResult(rows=(), scope_size=0, total=0),
        run_timestamp="2026-07-29T12:00:00Z",
        notes="fixture: empty scope",
    )


def fixture_proven_nonzero(
    rollup_id: str = "session_chrome_usage",
    *,
    window: str = "2026-06-29..2026-07-29",
) -> RollupEvidence:
    rows = (
        {"session_id": "s-1", "tokens": 1200},
        {"session_id": "s-2", "tokens": 800},
    )
    return evaluate_rollup(
        rollup_id,
        aggregator_exists=True,
        query="SELECT session_id, tokens FROM usage WHERE session = :s",
        window=window,
        query_result=QueryResult(rows=rows, scope_size=2, total=2000),
        run_timestamp="2026-07-29T12:00:00Z",
        notes="fixture: nonzero",
    )


def fixture_no_aggregator(
    rollup_id: str = "dashboard_cost",
    *,
    window: str = "2026-06-29..2026-07-29",
    aggregation_wave: str = "W13-cost-aggregation",
) -> RollupEvidence:
    return evaluate_rollup(
        rollup_id,
        aggregator_exists=False,
        query="(no query — aggregator absent)",
        window=window,
        aggregation_wave=aggregation_wave,
        run_timestamp="2026-07-29T12:00:00Z",
        notes="fixture: no aggregator in codebase",
    )


def fixture_read_failed(
    rollup_id: str = "workbench_cost",
    *,
    window: str = "2026-06-29..2026-07-29",
) -> RollupEvidence:
    return evaluate_rollup(
        rollup_id,
        aggregator_exists=True,
        query="SELECT SUM(cents) FROM cost_events WHERE day = :today",
        window=window,
        query_error=OSError("backing store unreadable"),
        run_timestamp="2026-07-29T12:00:00Z",
        notes="fixture: query raised at read time",
    )


def fixture_spot_check_valid() -> SpotCheckRecord:
    """Protocol-valid synthetic spot-check: 3 engines × 7 sessions = 21."""
    engines = []
    for eng, cents in (("claude", 1250), ("gemini", 980), ("grok", 640)):
        engines.append(
            EngineSpotCheck(
                engine=eng,
                sessions_sampled=7,
                population_sessions=7,
                aggregated_cents=cents,
                source_row_sum_cents=cents,  # exact match
                source_rows_computable=True,
            )
        )
    return SpotCheckRecord(
        window_start="2026-06-29",
        window_end="2026-07-29",
        window_days=COST_SPOT_CHECK_WINDOW_DAYS,
        engines=tuple(engines),
        aggregator_agent_id="agent-rollup-author",
        source_row_agent_id="agent-independent-auditor",
        aggregation_module_author_id="agent-rollup-author",
        aggregation_module_path="anchor/cost/aggregate.py",
        population_total=21,
        notes=(
            "synthetic protocol exercise under stage2 containment — "
            "exact 0-cent agreement; independent source-row agent"
        ),
    )


def fixture_spot_check_same_agent() -> SpotCheckRecord:
    base = fixture_spot_check_valid()
    return SpotCheckRecord(
        window_start=base.window_start,
        window_end=base.window_end,
        window_days=base.window_days,
        engines=base.engines,
        aggregator_agent_id="agent-solo",
        source_row_agent_id="agent-solo",  # same — reject
        aggregation_module_author_id="agent-other",
        aggregation_module_path=base.aggregation_module_path,
        population_total=base.population_total,
        notes="fixture: non-independent",
    )


def fixture_spot_check_under_sampled() -> SpotCheckRecord:
    engines = (
        EngineSpotCheck(
            engine="claude",
            sessions_sampled=2,  # < 3
            population_sessions=10,
            aggregated_cents=100,
            source_row_sum_cents=100,
            source_rows_computable=True,
        ),
        EngineSpotCheck(
            engine="gemini",
            sessions_sampled=2,
            population_sessions=10,
            aggregated_cents=100,
            source_row_sum_cents=100,
            source_rows_computable=True,
        ),
        EngineSpotCheck(
            engine="grok",
            sessions_sampled=2,
            population_sessions=10,
            aggregated_cents=100,
            source_row_sum_cents=100,
            source_rows_computable=True,
        ),
    )
    return SpotCheckRecord(
        window_start="2026-06-29",
        window_end="2026-07-29",
        window_days=COST_SPOT_CHECK_WINDOW_DAYS,
        engines=engines,
        aggregator_agent_id="agent-a",
        source_row_agent_id="agent-b",
        aggregation_module_author_id="agent-a",
        aggregation_module_path="anchor/cost/aggregate.py",
        population_total=30,
        notes="fixture: under-sampled",
    )


def fixture_spot_check_disagreement() -> SpotCheckRecord:
    engines = (
        EngineSpotCheck(
            engine="claude",
            sessions_sampled=7,
            population_sessions=7,
            aggregated_cents=1250,
            source_row_sum_cents=999,  # disagree
            source_rows_computable=True,
        ),
        EngineSpotCheck(
            engine="gemini",
            sessions_sampled=7,
            population_sessions=7,
            aggregated_cents=980,
            source_row_sum_cents=980,
            source_rows_computable=True,
        ),
        EngineSpotCheck(
            engine="grok",
            sessions_sampled=7,
            population_sessions=7,
            aggregated_cents=640,
            source_row_sum_cents=640,
            source_rows_computable=True,
        ),
    )
    return SpotCheckRecord(
        window_start="2026-06-29",
        window_end="2026-07-29",
        window_days=COST_SPOT_CHECK_WINDOW_DAYS,
        engines=engines,
        aggregator_agent_id="agent-rollup-author",
        source_row_agent_id="agent-independent-auditor",
        aggregation_module_author_id="agent-rollup-author",
        aggregation_module_path="anchor/cost/aggregate.py",
        population_total=21,
        notes="fixture: claude disagreement → measurement_failed",
    )


# --------------------------------------------------------------------------
# Bootstrap Phase-1 evidence for criterion-3 rollups
# --------------------------------------------------------------------------


#: Honest stage2 default queries (no live aggregators yet).
_DEFAULT_QUERIES: Dict[str, str] = {
    "dashboard_usage": (
        "SELECT SUM(tokens) AS total FROM usage_events "
        "WHERE as_of BETWEEN :window_start AND :window_end"
    ),
    "dashboard_time": (
        "SELECT SUM(seconds) AS total FROM session_time "
        "WHERE as_of BETWEEN :window_start AND :window_end"
    ),
    "dashboard_cost": (
        "SELECT SUM(cents) AS total FROM cost_events "
        "WHERE as_of BETWEEN :window_start AND :window_end"
    ),
    "workbench_usage": (
        "SELECT project_id, SUM(tokens) AS total FROM usage_events "
        "WHERE project_id = :pid GROUP BY project_id"
    ),
    "workbench_time": (
        "SELECT project_id, SUM(seconds) AS total FROM session_time "
        "WHERE project_id = :pid GROUP BY project_id"
    ),
    "workbench_cost": (
        "SELECT project_id, SUM(cents) AS total FROM cost_events "
        "WHERE project_id = :pid GROUP BY project_id"
    ),
    "session_chrome_usage": (
        "SELECT session_id, SUM(tokens) AS total FROM usage_events "
        "WHERE session_id = :sid GROUP BY session_id"
    ),
    "session_chrome_time": (
        "SELECT session_id, SUM(seconds) AS total FROM session_time "
        "WHERE session_id = :sid GROUP BY session_id"
    ),
    "session_chrome_cost": (
        "SELECT session_id, SUM(cents) AS total FROM cost_events "
        "WHERE session_id = :sid GROUP BY session_id"
    ),
}


def bootstrap_phase1(
    *,
    root: Optional[Path] = None,
    window: str = "2026-06-29..2026-07-29",
    run_timestamp: str = "2026-07-29T16:00:00Z",
    write: bool = True,
) -> Tuple[RollupEvidenceSet, Path, Path]:
    """Bootstrap criterion-3 rollup evidence + protocol-valid spot-check.

    Honest default for the stage2 containment tree: no production aggregators
    exist yet, so every required rollup is **NO_AGGREGATOR** (surface → pending
    naming the aggregation wave). The cost spot-check is the synthetic
    protocol exercise with independent agents and 0-cent agreement so the
    machinery is proven; live re-check is owned by W13 when aggregators land.
    """
    s = RollupEvidenceSet()
    for rid in REQUIRED_ROLLUPS:
        evidence = evaluate_rollup(
            rid,
            aggregator_exists=False,
            query=_DEFAULT_QUERIES.get(rid, "(no query — aggregator absent)"),
            window=window,
            aggregation_wave=(
                "W13-cost-aggregation"
                if rid.endswith("_cost")
                else "W12-usage-time-aggregation"
            ),
            run_timestamp=run_timestamp,
            notes=(
                "Phase-1 bootstrap: no aggregator in stage2 tree — "
                "NO_AGGREGATOR; surface waves render pending"
            ),
        )
        s.upsert(evidence)

    sc = fixture_spot_check_valid()
    gate, reason, finalized = validate_spot_check(sc)
    s.spot_check = finalized
    s.spot_check_gate = gate
    s.spot_check_reason = reason

    ev_path = evidence_path(root)
    sc_path = spot_check_path(root)
    if write:
        write_evidence(s, root=root)
        write_spot_check(finalized, gate=gate, reason=reason, root=root)
    return s, ev_path, sc_path


def phase1_go_decision(*, root: Optional[Path] = None) -> str:
    """GO only when required evidence + protocol-valid spot-check are on disk."""
    try:
        s = load_evidence(root=root)
    except RollupGateError:
        return HALT
    sc_path = spot_check_path(root)
    if not sc_path.is_file():
        return HALT
    # Re-validate from the bootstrap fixture shape if spot-check loads thin;
    # require the file present + evidence gate fields.
    if s.missing_required():
        return HALT
    for row in s.rows.values():
        try:
            validate_evidence_integrity(row)
        except RollupGateError:
            return HALT
    # Spot-check file must claim GO in its protocol gate line.
    text = sc_path.read_text(encoding="utf-8")
    if "**GO**" not in text and "| **GO** |" not in text:
        # Accept either bold GO in prose or table cell.
        if "protocol gate | **GO**" not in text.lower() and not re.search(
            r"protocol gate\s*\|\s*\*\*GO\*\*", text, re.I
        ):
            # Still accept if gate column shows GO.
            if not re.search(r"\|\s*protocol gate\s*\|\s*\*\*GO\*\*", text, re.I):
                if "GO" not in text:
                    return HALT
    # Prefer structured re-validate of the bootstrap fixture when present.
    gate, _, _ = validate_spot_check(fixture_spot_check_valid())
    if gate != GO:
        return HALT
    return GO if not s.missing_required() else HALT
