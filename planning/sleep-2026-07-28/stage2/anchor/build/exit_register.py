"""Exit register engine + terminal status-string generator — W2, Phase 0.

Makes the six exits E1–E6 machine-enforced rather than prose:

* **Unsigned exit is a HALT.** A row without John's dated confirmation is
  refused; it is never written as a silent default.
* **E2 is illegal for dollars.** Cost criteria render ``measurement_failed``;
  they never ship a provisional dollar figure under an as_of stamp.
* **E6 is closed** for the four North-Star violation classes: dead control,
  silent zero, mislabelled empty, raw-binary preview.
* **No exit may be justified by another exit.** E1 needs ABSENT + independent
  absence transcript (STUB is never enough); E2 needs a proven accessor;
  E3 may not ride on an upstream E1.
* **Conjunction scoring** forces ``HALT_REBASELINE`` at two exits on one
  criterion or four signed exits across the whole build.

``terminal_status`` emits only the structural CANDIDATE-MET phrase while any
exit is signed or while S1 has no recorded PASS. The unqualified phrase
``ten criteria met`` is unreachable until both conditions clear — no amount
of green structure can emit it.

Paths are relative to the stage2 containment root (or an injected ``root``).
No absolute host paths are hard-coded.
"""
from __future__ import annotations

import os
import re
from dataclasses import asdict, dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple, Union

# --------------------------------------------------------------------------
# Public constants
# --------------------------------------------------------------------------

GO = "GO"
HALT = "HALT"
HALT_REBASELINE = "HALT_REBASELINE"
OK = "OK"

#: Conjunction ceilings (named numeric bounds from the frozen plan header).
MAX_EXITS_PER_CRITERION = 2
MAX_EXITS_ACROSS_BUILD = 4

#: Verbatim IllegalExit message for E2-on-cost (asserted by the wave GWT).
E2_DOLLARS_MESSAGE = (
    "E2 does not apply to dollars — cost surfaces render measurement_failed"
)

#: STUB-justified E1 rejection (asserted by the wave GWT).
E1_STUB_MESSAGE = (
    "E1 cannot be justified by a STUB verdict — requires either a "
    "'build it' wave or an ABSENT verdict with an independent absence transcript"
)

E2_UNPROVEN_ACCESSOR_MESSAGE = (
    "E2 cannot be justified by an unproven accessor — accessor must be proven"
)

E3_UPSTREAM_E1_MESSAGE = (
    "E3 cannot be justified by an upstream E1 — exit-justified-by-exit is illegal"
)

EXIT_JUSTIFIED_BY_EXIT_MESSAGE = (
    "no exit may be justified by another exit"
)

UNSIGNED_MESSAGE = "unsigned exit is a HALT — John's dated confirmation is required"

E6_CLOSED_MESSAGE = (
    "E6 is closed for North-Star violation classes "
    "(dead control / silent zero / mislabelled empty / raw-binary preview)"
)

#: Binding status phrases (verbatim — tests assert exact strings).
STATUS_CANDIDATE_MET_PREFIX = (
    "ten criteria CANDIDATE-MET (structural, rendered-string level)"
)
STATUS_UNQUALIFIED = "ten criteria met"
STATUS_NORTH_STAR_PENDING = "North Star pending S1"
STATUS_NORTH_STAR_MET = "North Star met (S1 PASS)"

#: Document relative path under the containment root.
REGISTER_RELPATH = os.path.join("artifacts", "EXIT-REGISTER.md")

#: The four North-Star violation classes that close E6.
NS_VIOLATION_CLASSES: frozenset = frozenset(
    {
        "dead_control",
        "dead control",
        "silent_zero",
        "silent zero",
        "mislabelled_empty",
        "mislabelled empty",
        "raw_binary",
        "raw-binary",
        "raw binary",
        "raw-binary preview",
        "raw binary preview",
    }
)

#: Criterion tokens that mark a *cost / dollars* criterion (E2 illegal).
_COST_CRITERION_MARKERS: Tuple[str, ...] = (
    "cost",
    "dollar",
    "dollars",
    "cost-labelling",
    "cost_labelling",
    "cost labelling",
    "cost-labeling",
    "cost_state",
)

_ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

_EXIT_ID_IN_TEXT = re.compile(r"\bE[1-6]\b")


# --------------------------------------------------------------------------
# Enums + errors
# --------------------------------------------------------------------------


class ExitId(str, Enum):
    """The only legal exits in this build — enumerated, not improvised."""

    E1 = "E1"  # not available on this build
    E2 = "E2"  # provisional data
    E3 = "E3"  # documented with reason (out-of-criteria surface)
    E4 = "E4"  # reduced-instrument path
    E5 = "E5"  # not verified — awaiting John
    E6 = "E6"  # S1 finding routed to follow-on

    @property
    def label(self) -> str:
        return {
            ExitId.E1: "not available on this build",
            ExitId.E2: "provisional data",
            ExitId.E3: "documented with reason",
            ExitId.E4: "reduced-instrument path",
            ExitId.E5: "not verified — awaiting John",
            ExitId.E6: "S1 finding routed to follow-on",
        }[self]


class IllegalExit(Exception):
    """Raised when a register row or justification violates a hard rule."""

    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


class UnsignedExit(IllegalExit):
    """Raised when a row lacks John's dated confirmation (unsigned = HALT)."""


# --------------------------------------------------------------------------
# Register row schema
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class ExitRegisterRow:
    """One signed exit: exit id, criterion, forcing evidence, user-visible
    substitute, date, and John's confirmation.

    Fields match the frozen W2 contract. An incomplete or unsigned row is
    rejected by :func:`validate` and never written.
    """

    exit_id: ExitId
    criterion: str
    forcing_evidence: str
    user_sees_instead: str
    date: str
    john_confirmation: str
    #: Optional free-form justification blob inspected by validate_justification.
    justification: str = ""
    #: Inventory verdict if cited (PRESENT | STUB | ABSENT | …).
    inventory_verdict: Optional[str] = None
    #: Whether the accessor behind provisional data is proven.
    accessor_proven: Optional[bool] = None
    #: S1 / finding class when exit is E6 (e.g. dead_control).
    finding_class: Optional[str] = None
    #: Upstream exit id if any (always illegal as justification).
    justified_by_exit: Optional[str] = None

    def as_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["exit_id"] = self.exit_id.value
        return d


def parse_exit_id(value: Union[ExitId, str]) -> ExitId:
    if isinstance(value, ExitId):
        return value
    text = str(value).strip().upper()
    try:
        return ExitId[text]
    except KeyError as exc:
        raise IllegalExit("unknown exit id %r — only E1–E6 are legal" % value) from exc


def make_row(
    exit_id: Union[ExitId, str],
    criterion: str,
    forcing_evidence: str,
    user_sees_instead: str,
    date: str,
    john_confirmation: str = "",
    **kwargs: Any,
) -> ExitRegisterRow:
    """Build a row (does not validate). Prefer :func:`validate` before write."""
    return ExitRegisterRow(
        exit_id=parse_exit_id(exit_id),
        criterion=str(criterion or ""),
        forcing_evidence=str(forcing_evidence or ""),
        user_sees_instead=str(user_sees_instead or ""),
        date=str(date or ""),
        john_confirmation=str(john_confirmation or ""),
        justification=str(kwargs.get("justification") or ""),
        inventory_verdict=(
            str(kwargs["inventory_verdict"]).upper()
            if kwargs.get("inventory_verdict") is not None
            else None
        ),
        accessor_proven=kwargs.get("accessor_proven"),
        finding_class=kwargs.get("finding_class"),
        justified_by_exit=(
            str(kwargs["justified_by_exit"]).upper()
            if kwargs.get("justified_by_exit") is not None
            else None
        ),
    )


# --------------------------------------------------------------------------
# Criterion / finding helpers
# --------------------------------------------------------------------------


def is_cost_criterion(criterion: str) -> bool:
    """True when the criterion is a cost / dollars surface (E2 illegal)."""
    text = (criterion or "").strip().lower().replace("_", "-")
    if not text:
        return False
    # Explicit cost-labelling (wave GWT).
    if "cost" in text and ("label" in text or "labelling" in text or "labeling" in text):
        return True
    for marker in _COST_CRITERION_MARKERS:
        if marker in text:
            return True
    return False


def is_ns_violation_class(finding_class: Optional[str]) -> bool:
    if finding_class is None:
        return False
    text = str(finding_class).strip().lower().replace("-", " ").replace("_", " ")
    text = " ".join(text.split())
    normalized = {
        "dead control",
        "silent zero",
        "mislabelled empty",
        "mislabeled empty",
        "raw binary",
        "raw binary preview",
    }
    if text in normalized:
        return True
    # Also accept hyphenated / underscored original tokens.
    raw = str(finding_class).strip().lower()
    return raw in NS_VIOLATION_CLASSES or any(
        token in raw
        for token in (
            "dead_control",
            "dead-control",
            "silent_zero",
            "silent-zero",
            "mislabelled_empty",
            "mislabelled-empty",
            "raw_binary",
            "raw-binary",
        )
    )


def _signature_is_valid(date: str, john_confirmation: str) -> bool:
    if not isinstance(date, str) or not _ISO_DATE.match(date.strip()):
        return False
    if not str(john_confirmation or "").strip():
        return False
    return True


def _text_cites_exit(text: str) -> Optional[str]:
    m = _EXIT_ID_IN_TEXT.search(text or "")
    return m.group(0) if m else None


# --------------------------------------------------------------------------
# validate_justification
# --------------------------------------------------------------------------


def validate_justification(
    exit_id: Union[ExitId, str],
    *,
    inventory_verdict: Optional[str] = None,
    accessor_proven: Optional[bool] = None,
    justified_by_exit: Optional[str] = None,
    justification: str = "",
    finding_class: Optional[str] = None,
    criterion: str = "",
    forcing_evidence: str = "",
) -> None:
    """Reject illegal justifications without writing a row.

    Rules (frozen plan + master-plan exit register):

    * E1 justified by STUB → reject (need 'build it' wave or ABSENT + transcript).
    * E2 justified by unproven accessor → reject.
    * E3 justified by an upstream E1 → reject.
    * Any exit justified by another exit id → reject.
    * E6 for a North-Star violation class → reject.
    """
    eid = parse_exit_id(exit_id)
    blob = " ".join(
        [
            str(justification or ""),
            str(forcing_evidence or ""),
            str(justified_by_exit or ""),
        ]
    )

    # Explicit upstream exit pointer.
    if justified_by_exit:
        other = str(justified_by_exit).strip().upper()
        if other in {e.value for e in ExitId}:
            if eid == ExitId.E3 and other == ExitId.E1.value:
                raise IllegalExit(E3_UPSTREAM_E1_MESSAGE)
            raise IllegalExit(EXIT_JUSTIFIED_BY_EXIT_MESSAGE)

    # Free-text "justified by E…"
    cited = _text_cites_exit(blob)
    if cited and cited != eid.value:
        if eid == ExitId.E3 and cited == ExitId.E1.value:
            raise IllegalExit(E3_UPSTREAM_E1_MESSAGE)
        raise IllegalExit(EXIT_JUSTIFIED_BY_EXIT_MESSAGE)

    if eid == ExitId.E1:
        verdict = (inventory_verdict or "").strip().upper()
        # STUB never authorizes E1.
        if verdict == "STUB" or re.search(r"\bSTUB\b", blob, re.IGNORECASE):
            raise IllegalExit(E1_STUB_MESSAGE)
        # If a verdict is offered, it must be ABSENT with evidence of absence.
        if verdict and verdict != "ABSENT":
            raise IllegalExit(E1_STUB_MESSAGE)
        if verdict == "ABSENT":
            evidence = (forcing_evidence or justification or "").strip()
            if not evidence:
                raise IllegalExit(
                    "E1 with ABSENT requires an independent absence transcript"
                )
            low = evidence.lower()
            if "transcript" not in low and "absence" not in low:
                raise IllegalExit(
                    "E1 with ABSENT requires an independent absence transcript"
                )

    if eid == ExitId.E2:
        if accessor_proven is False:
            raise IllegalExit(E2_UNPROVEN_ACCESSOR_MESSAGE)
        if re.search(r"unproven\s+accessor", blob, re.IGNORECASE):
            raise IllegalExit(E2_UNPROVEN_ACCESSOR_MESSAGE)
        if is_cost_criterion(criterion):
            raise IllegalExit(E2_DOLLARS_MESSAGE)

    if eid == ExitId.E3:
        if re.search(r"upstream\s+E1|\bE1\b.*(justif|took|took\s+E1)", blob, re.I):
            raise IllegalExit(E3_UPSTREAM_E1_MESSAGE)
        if re.search(r"took\s+E1|wave that would have fixed.*E1", blob, re.I):
            raise IllegalExit(E3_UPSTREAM_E1_MESSAGE)

    if eid == ExitId.E6:
        if is_ns_violation_class(finding_class):
            raise IllegalExit(E6_CLOSED_MESSAGE)
        # Also scan free text for the four classes.
        low = blob.lower()
        for phrase in (
            "dead control",
            "silent zero",
            "mislabelled empty",
            "mislabeled empty",
            "raw-binary",
            "raw binary",
        ):
            if phrase in low:
                raise IllegalExit(E6_CLOSED_MESSAGE)


# --------------------------------------------------------------------------
# validate (signature + hard rules)
# --------------------------------------------------------------------------


def validate(row: ExitRegisterRow) -> ExitRegisterRow:
    """Validate a register row. Raises IllegalExit; never writes.

    Checks: schema completeness, John's signature, E2-on-cost, E6 closed
    classes, and justification rules.
    """
    if not isinstance(row, ExitRegisterRow):
        raise IllegalExit("register row must be an ExitRegisterRow")

    if not str(row.criterion or "").strip():
        raise IllegalExit("register row requires a criterion")
    if not str(row.forcing_evidence or "").strip():
        raise IllegalExit("register row requires forcing evidence")
    if not str(row.user_sees_instead or "").strip():
        raise IllegalExit("register row requires what the user sees instead")

    if not _signature_is_valid(row.date, row.john_confirmation):
        raise UnsignedExit(UNSIGNED_MESSAGE)

    # E2 never on dollars / cost-labelling (even with a valid signature + as_of).
    if row.exit_id == ExitId.E2 and is_cost_criterion(row.criterion):
        raise IllegalExit(E2_DOLLARS_MESSAGE)

    # E6 closed for the four NS classes (field or evidence text).
    if row.exit_id == ExitId.E6:
        if is_ns_violation_class(row.finding_class):
            raise IllegalExit(E6_CLOSED_MESSAGE)
        low = (row.forcing_evidence or "").lower() + " " + (row.justification or "").lower()
        for phrase in (
            "dead control",
            "silent zero",
            "mislabelled empty",
            "mislabeled empty",
            "raw-binary",
            "raw binary",
        ):
            if phrase in low:
                raise IllegalExit(E6_CLOSED_MESSAGE)

    validate_justification(
        row.exit_id,
        inventory_verdict=row.inventory_verdict,
        accessor_proven=row.accessor_proven,
        justified_by_exit=row.justified_by_exit,
        justification=row.justification,
        finding_class=row.finding_class,
        criterion=row.criterion,
        forcing_evidence=row.forcing_evidence,
    )
    return row


# --------------------------------------------------------------------------
# score_conjunction
# --------------------------------------------------------------------------


def score_conjunction(
    rows: Sequence[ExitRegisterRow],
    *,
    pending: Optional[ExitRegisterRow] = None,
    rebaseline_recorded: bool = False,
) -> str:
    """Score signed exits as a conjunction.

    Returns:

    * ``OK`` — under both ceilings
    * ``HALT_REBASELINE`` — ≥2 on one criterion, or ≥4 across the build
      (unless John has already recorded an explicit re-baseline for this set)

    ``pending`` is a row about to be signed; it is counted with the existing
    set so a fourth signing attempt is caught before write.
    """
    signed: List[ExitRegisterRow] = list(rows)
    if pending is not None:
        signed = signed + [pending]

    if rebaseline_recorded:
        # Explicit re-baseline clears the conjunction halt for this set.
        return OK

    by_criterion: Dict[str, int] = {}
    for r in signed:
        key = (r.criterion or "").strip().lower()
        by_criterion[key] = by_criterion.get(key, 0) + 1
        if by_criterion[key] >= MAX_EXITS_PER_CRITERION:
            return HALT_REBASELINE

    if len(signed) >= MAX_EXITS_ACROSS_BUILD:
        return HALT_REBASELINE

    return OK


def may_start_subsequent_wave(
    rows: Sequence[ExitRegisterRow],
    *,
    rebaseline_recorded: bool = False,
) -> bool:
    """False when conjunction scoring demands re-baseline before any new wave."""
    return score_conjunction(rows, rebaseline_recorded=rebaseline_recorded) == OK


# --------------------------------------------------------------------------
# terminal_status
# --------------------------------------------------------------------------


def _format_exit_ids(rows: Sequence[ExitRegisterRow]) -> str:
    ids = sorted({r.exit_id.value for r in rows}, key=lambda x: int(x[1:]))
    return ",".join(ids)


def terminal_status(
    rows: Sequence[ExitRegisterRow] = (),
    *,
    s1_verdict: Optional[str] = None,
    signed_exits: Optional[Sequence[Union[ExitId, str]]] = None,
) -> str:
    """Emit the binding terminal status string.

    Default (any exits signed, or S1 not PASS)::

        ten criteria CANDIDATE-MET (structural, rendered-string level) with N
        signed exits (E<ids>); North Star pending S1

    With zero signed exits **and** S1 PASS only::

        ten criteria met

    (optionally with S1 PASS attached). The unqualified phrase is unreachable
    while any exit is signed or while S1 has no recorded PASS.
    """
    signed_rows = list(rows)
    if signed_exits is not None and not signed_rows:
        # Allow callers to pass bare ids when rows are not materialised.
        signed_rows = [
            make_row(
                eid,
                criterion="(status-only)",
                forcing_evidence="status-only",
                user_sees_instead="status-only",
                date="1970-01-01",
                john_confirmation="status-only",
            )
            for eid in signed_exits
        ]

    n = len(signed_rows)
    s1 = (s1_verdict or "").strip().upper()
    s1_pass = s1 in {"PASS", "PASSED", "S1 PASS", "S1_PASS"}

    if n == 0 and s1_pass:
        return STATUS_UNQUALIFIED

    if n == 0:
        return (
            "%s with 0 signed exits (); %s"
            % (STATUS_CANDIDATE_MET_PREFIX, STATUS_NORTH_STAR_PENDING)
        )

    ids = _format_exit_ids(signed_rows)
    return (
        "%s with %d signed exits (%s); %s"
        % (STATUS_CANDIDATE_MET_PREFIX, n, ids, STATUS_NORTH_STAR_PENDING)
    )


def unqualified_status_reachable(
    rows: Sequence[ExitRegisterRow] = (),
    *,
    s1_verdict: Optional[str] = None,
) -> bool:
    """True only when terminal_status may emit the unqualified phrase."""
    s1 = (s1_verdict or "").strip().upper()
    return len(rows) == 0 and s1 in {"PASS", "PASSED", "S1 PASS", "S1_PASS"}


def is_s1_pass_verdict(s1_verdict: Optional[str]) -> bool:
    """True when *s1_verdict* is an explicit S1 PASS token (not PENDING)."""
    s1 = (s1_verdict or "").strip().upper()
    return s1 in {"PASS", "PASSED", "S1 PASS", "S1_PASS"}


def terminal_status_with_s1_attachment(
    rows: Sequence[ExitRegisterRow] = (),
    *,
    s1_verdict: Optional[str] = None,
    signed_exits: Optional[Sequence[Union[ExitId, str]]] = None,
) -> str:
    """Like :func:`terminal_status`, but when the unqualified phrase is
    reachable, append the North Star met stamp so S1's PASS is visible on the
    emitted line.

    Default :func:`terminal_status` keeps the exact W2 phrase
    ``ten criteria met`` for the zero-exit + S1 PASS path (so existing tests
    stay stable). W22 display / gate paths that want the PASS verdict
    *attached* call this helper instead.

    When the unqualified phrase is **not** reachable, the result is identical
    to :func:`terminal_status` (CANDIDATE-MET + North Star pending S1).
    """
    base = terminal_status(rows, s1_verdict=s1_verdict, signed_exits=signed_exits)
    if base == STATUS_UNQUALIFIED and is_s1_pass_verdict(s1_verdict):
        return "%s; %s" % (STATUS_UNQUALIFIED, STATUS_NORTH_STAR_MET)
    return base


def resolve_s1_verdict(
    s1_verdict: Optional[str] = None,
    *,
    root: Optional[Path] = None,
    default: str = "PENDING",
) -> Optional[str]:
    """Resolve S1 verdict for status emission.

    Preference order:

    1. Explicit *s1_verdict* argument (test injection / live recorder).
    2. ``artifacts/S1-VALIDATION.md`` under *root* (or containment root).
    3. *default* (PENDING) — S1 has not been run; never invent PASS.
    """
    if s1_verdict is not None and str(s1_verdict).strip():
        return str(s1_verdict).strip()
    try:
        from anchor.build import s1_findings as _s1f  # local import: W22 module

        text_verdict = _s1f.read_s1_verdict(root=root)
        if text_verdict and str(text_verdict).strip():
            return str(text_verdict).strip()
    except Exception:
        # s1_findings missing or unreadable → fall through to default.
        pass
    return default


def emit_terminal_status(
    rows: Sequence[ExitRegisterRow] = (),
    *,
    s1_verdict: Optional[str] = None,
    root: Optional[Path] = None,
    signed_exits: Optional[Sequence[Union[ExitId, str]]] = None,
    attach_s1_pass: bool = False,
) -> str:
    """Emit terminal status for the build, resolving S1 from injection or file.

    Default *s1_verdict* is unresolved → read S1-VALIDATION.md → PENDING.
    Unqualified phrasing only when resolved verdict is PASS and zero exits.
    Set *attach_s1_pass* True to append ``North Star met (S1 PASS)`` when the
    unqualified phrase is reached (W22 GWT display form).
    """
    resolved = resolve_s1_verdict(s1_verdict, root=root)
    # PENDING / FAIL must not unlock unqualified; only PASS tokens do.
    if is_s1_pass_verdict(resolved):
        verdict_for_status: Optional[str] = "PASS"
    else:
        verdict_for_status = None
    if attach_s1_pass:
        return terminal_status_with_s1_attachment(
            rows, s1_verdict=verdict_for_status, signed_exits=signed_exits
        )
    return terminal_status(
        rows, s1_verdict=verdict_for_status, signed_exits=signed_exits
    )


# --------------------------------------------------------------------------
# In-memory register + file ledger
# --------------------------------------------------------------------------


@dataclass
class ExitRegister:
    """In-memory exit register with optional on-disk ledger path.

    Starts empty (zero signed exits). ``try_sign`` validates, scores the
    conjunction, and only then appends — illegal or re-baseline-forcing rows
    are not written.
    """

    rows: List[ExitRegisterRow] = field(default_factory=list)
    rebaseline_recorded: bool = False
    s1_verdict: Optional[str] = None
    path: Optional[Path] = None

    def signed_count(self) -> int:
        return len(self.rows)

    def validate_row(self, row: ExitRegisterRow) -> ExitRegisterRow:
        return validate(row)

    def try_sign(self, row: ExitRegisterRow) -> ExitRegisterRow:
        """Validate + conjunction-score; write only on OK.

        Raises IllegalExit on rule failure. Raises IllegalExit with a
        re-baseline message when score_conjunction returns HALT_REBASELINE.
        """
        validated = validate(row)
        score = score_conjunction(
            self.rows,
            pending=validated,
            rebaseline_recorded=self.rebaseline_recorded,
        )
        if score == HALT_REBASELINE:
            raise IllegalExit(
                "HALT_REBASELINE — no subsequent wave may start until John "
                "records an explicit re-baseline"
            )
        self.rows.append(validated)
        return validated

    def record_rebaseline(self) -> None:
        """John's explicit re-baseline clears the conjunction halt."""
        self.rebaseline_recorded = True

    def score(self) -> str:
        return score_conjunction(
            self.rows, rebaseline_recorded=self.rebaseline_recorded
        )

    def status(self) -> str:
        return terminal_status(self.rows, s1_verdict=self.s1_verdict)

    def status_with_s1_attachment(self) -> str:
        """Terminal status with S1 PASS stamp attached when unqualified."""
        return terminal_status_with_s1_attachment(
            self.rows, s1_verdict=self.s1_verdict
        )

    def may_start_wave(self) -> bool:
        return may_start_subsequent_wave(
            self.rows, rebaseline_recorded=self.rebaseline_recorded
        )


def empty_register_markdown() -> str:
    """Canonical EXIT-REGISTER.md body — zero signed exits at plan/W2 time."""
    return (
        "# Exit Register\n"
        "\n"
        "Build: Anchor sleep cycle 2026-07-28 (v1.2)\n"
        "Wave: W2 — Phase 0: Exit register engine + status-string generator\n"
        "\n"
        "## Signed exits\n"
        "\n"
        "**Zero signed exits.** At plan time and at W2 delivery John has signed "
        "for none. None are pre-authorized; every exit is signed live in the "
        "wave that needs it, via `anchor.build.exit_register`.\n"
        "\n"
        "| exit id | criterion | forcing evidence | user sees instead | date | John confirmation |\n"
        "|---------|-----------|------------------|-------------------|------|-------------------|\n"
        "| _(none)_ | — | — | — | — | — |\n"
        "\n"
        "## Binding rules (machine-enforced in exit_register.py)\n"
        "\n"
        "- E1 `not available on this build` — ABSENT + independent absence transcript; STUB never authorizes E1\n"
        "- E2 `provisional data` — usage/time only; **illegal for dollars / cost-labelling**\n"
        "- E3 `documented with reason` — surface already honest or removed; not justified by upstream E1\n"
        "- E4 `reduced-instrument path` — signed narrowing to the named lighter forms\n"
        "- E5 `not verified — awaiting John` — not available on the W1 task triple\n"
        "- E6 `S1 finding routed to follow-on` — **closed** for dead control / silent zero / mislabelled empty / raw-binary preview\n"
        "- Unsigned exit = HALT\n"
        "- Conjunction: 2 exits on one criterion, or 4 across the build → `HALT_REBASELINE`\n"
        "- Terminal status: structural CANDIDATE-MET phrase until N==0 **and** S1 PASS; unqualified `ten criteria met` only then\n"
    )


def register_path(root: Optional[Path] = None) -> Path:
    if root is not None:
        return Path(root) / REGISTER_RELPATH
    try:
        from tools import containment_smoke  # type: ignore
    except ImportError:
        # When imported as a package under stage2, fall back to this file's tree.
        here = Path(__file__).resolve()
        # anchor/build/exit_register.py → stage2 root is parents[2]
        return here.parents[2] / REGISTER_RELPATH
    return containment_smoke.containment_root() / REGISTER_RELPATH


def write_empty_register(root: Optional[Path] = None, *, force: bool = False) -> Path:
    """Write EXIT-REGISTER.md with zero signed exits. Idempotent unless force."""
    path = register_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and not force:
        text = path.read_text(encoding="utf-8")
        if "Zero signed exits" in text or "_(none)_" in text:
            return path
    path.write_text(empty_register_markdown(), encoding="utf-8")
    return path


def load_signed_count_from_markdown(text: str) -> int:
    """Count signed data rows in EXIT-REGISTER.md (excludes the _(none)_ placeholder)."""
    count = 0
    for line in text.splitlines():
        line = line.strip()
        if not line.startswith("|"):
            continue
        if line.startswith("|---") or line.startswith("| exit"):
            continue
        if "_(none)_" in line or line.startswith("| —"):
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        if cells and cells[0] in {e.value for e in ExitId}:
            count += 1
    return count


# --------------------------------------------------------------------------
# CLI (optional smoke — not required by the wave gate)
# --------------------------------------------------------------------------


def main(argv: Optional[Sequence[str]] = None) -> int:
    import sys

    args = list(sys.argv[1:] if argv is None else argv)
    path = write_empty_register()
    reg = ExitRegister()
    status = reg.status()
    print("register:", path.as_posix() if hasattr(path, "as_posix") else str(path))
    print("signed:", reg.signed_count())
    print("status:", status)
    if args and args[0] == "--check-empty":
        text = path.read_text(encoding="utf-8")
        n = load_signed_count_from_markdown(text)
        if n != 0:
            print("FAIL: expected zero signed exits, found", n)
            return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
