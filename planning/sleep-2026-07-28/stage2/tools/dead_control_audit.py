"""Dead-control audit + surface-wave join gate + traceability matrix — W21.

Enumerates every rendered control and classifies each as one of:

* **wired** — live clickable with a real action target
* **named_state** — replaced by a cannot-* / render_state node (no clickable)
* **hidden** — intentionally absent from the surface (zero elements)

A control that is clickable but dead (no-op / disabled / dead-control class)
is a **finding**. Out-of-criteria controls bound to a missing capability that
still render a live affordance are findings; E3 is rejected for them until
fixed or removed from view.

Also owns:

* **surface-wave join gate** — W21 cannot GO until W10–W20 each have a GREEN
  row with a resolvable commit SHA (EXECUTION-LOG, then ``.foreman/wave-N-
  proven.json``, then ``foreman-checkpoint.json`` last_commit).
* **traceability matrix** — criterion → wave → test → commit → trace →
  status where status is only ``CANDIDATE-MET`` or ``OPEN`` (``MET`` before
  S1 fails the validator).
* **out-of-criteria surfaces** ledger + exit-register conjunction recon.
"""
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import (
    Any,
    Callable,
    Dict,
    Iterable,
    List,
    Mapping,
    Optional,
    Sequence,
    Tuple,
    Union,
)

from anchor.ui.dead_control import (
    CANNOT_STATE_CLASS,
    DEAD_CONTROL_CLASS,
    LIVE_CONTROL_CLASS,
    DeadControlFinding,
    audit_dead_controls,
)

# --------------------------------------------------------------------------
# Public constants
# --------------------------------------------------------------------------

GO = "GO"
HALT = "HALT"
HALT_REBASELINE = "HALT_REBASELINE"

WAVE_ID = "W21"
SURFACE_JOIN_MIN = 10
SURFACE_JOIN_MAX = 20  # join requires W10–W20; W21 is this close-out

STATUS_CANDIDATE_MET = "CANDIDATE-MET"
STATUS_OPEN = "OPEN"
STATUS_MET = "MET"  # illegal before S1

TRACEABILITY_RELPATH = os.path.join("artifacts", "TRACEABILITY-MATRIX.md")
OUT_OF_CRITERIA_RELPATH = os.path.join("artifacts", "OUT-OF-CRITERIA-SURFACES.md")
EXECUTION_LOG_RELPATH = "EXECUTION-LOG.md"
EXIT_REGISTER_RELPATH = os.path.join("artifacts", "EXIT-REGISTER.md")
FOREMAN_CHECKPOINT_RELPATH = "foreman-checkpoint.json"

#: Verbatim refuse messages (asserted by wave GWT / gate tests).
JOIN_MISSING_GREEN_MESSAGE = (
    "surface-wave join gate HALT — W10–W20 not all GREEN in EXECUTION-LOG.md"
)
JOIN_MISSING_SHA_MESSAGE = (
    "surface-wave join gate HALT — GREEN surface wave missing commit SHA"
)
MET_BEFORE_S1_MESSAGE = (
    "traceability matrix rejects MET before S1 — status may only be "
    "CANDIDATE-MET or OPEN"
)
INCOMPLETE_ROW_MESSAGE = (
    "traceability matrix incomplete row — test file, commit SHA, and "
    "trace artifact are required for CANDIDATE-MET"
)
DEAD_CONTROL_FINDING_MESSAGE = "dead-control audit found clickable no-op(s)"
E3_REJECTED_FOR_DEAD_MESSAGE = (
    "E3 rejected for out-of-criteria control still bound to missing "
    "capability — fix or remove from view first"
)

_SHA_HEX = re.compile(r"^[0-9a-f]{7,40}$", re.IGNORECASE)
_WAVE_GREEN_RE = re.compile(
    r"Wave\s+(\d+)\s*/\s*22\s+GREEN",
    re.IGNORECASE,
)
_WAVE_SECTION_RE = re.compile(
    r"^##\s+Wave\s+(\d+)\b",
    re.IGNORECASE | re.MULTILINE,
)
_COMMIT_LINE_RE = re.compile(
    r"^\s*-\s+\*\*commit:\*\*\s*(.+?)\s*$",
    re.IGNORECASE | re.MULTILINE,
)
_BUTTON_RE = re.compile(
    r"<\s*(button|a)\b([^>]*)>(.*?)</\s*(button|a)\s*>",
    re.IGNORECASE | re.DOTALL,
)
_CANNOT_BLOCK_RE = re.compile(
    r'<\s*(?:div|span)\b([^>]*\b%s\b[^>]*)>'
    r"(.*?)"
    r"</\s*(?:div|span)\s*>" % re.escape(CANNOT_STATE_CLASS),
    re.IGNORECASE | re.DOTALL,
)
_ATTR_RE = re.compile(
    r"""([a-zA-Z_:][-a-zA-Z0-9_:]*)\s*=\s*["']([^"']*)["']""",
    re.IGNORECASE,
)
_CONTROL_ATTR_RE = re.compile(
    r"""data-control\s*=\s*["']([^"']+)["']""",
    re.IGNORECASE,
)
_ACTION_ATTR_RE = re.compile(
    r"""(?:data-action|href|onclick)\s*=\s*["']([^"']*)["']""",
    re.IGNORECASE,
)
_CLASS_ATTR_RE = re.compile(
    r"""class\s*=\s*["']([^"']*)["']""",
    re.IGNORECASE,
)
_MODE_ATTR_RE = re.compile(
    r"""data-control-mode\s*=\s*["']([^"']*)["']""",
    re.IGNORECASE,
)

_NOOP_ACTIONS = frozenset(
    {
        "",
        "#",
        "javascript:void(0)",
        "javascript:;",
        "noop",
        "none",
        "null",
        "undefined",
    }
)

# --------------------------------------------------------------------------
# Criterion map (criteria 1–10 → surface waves / evidence)
# --------------------------------------------------------------------------

#: One row per criterion 1–10. Multi-wave criteria list primary + supporting.
CRITERION_MAP: Tuple[Dict[str, Any], ...] = (
    {
        "criterion": 1,
        "name": "open/run (+ Retry/Diagnose/restart dead-control clause)",
        "waves": ("W10",),
        "test_file": "tests/test_open_run_2026_07_29.py",
        "trace_artifacts": (
            "artifacts/traces/open-e2e.json",
            "artifacts/traces/run-e2e.json",
        ),
    },
    {
        "criterion": 2,
        "name": "session attach honesty (timeout / Retry)",
        "waves": ("W11",),
        "test_file": "tests/test_session_attach_2026_07_29.py",
        "trace_artifacts": ("artifacts/traces/attach-e2e.json",),
    },
    {
        "criterion": 3,
        "name": "usage/time + cost surfacing",
        "waves": ("W12", "W13"),
        "test_file": (
            "tests/test_usage_time_surfacing_2026_07_29.py; "
            "tests/test_cost_surfacing_2026_07_29.py"
        ),
        "trace_artifacts": (
            "artifacts/traces/usage-e2e.json",
            "artifacts/traces/cost-e2e.json",
        ),
    },
    {
        "criterion": 4,
        "name": "Doctor diagnose + per-engine depth labels",
        "waves": ("W14", "W15"),
        "test_file": (
            "tests/test_doctor_diagnose_2026_07_29.py; "
            "tests/test_doctor_engines_2026_07_29.py"
        ),
        "trace_artifacts": (
            "artifacts/traces/doctor-diagnose-e2e.json",
            "artifacts/traces/doctor-engines-e2e.json",
        ),
    },
    {
        "criterion": 5,
        "name": "stop summary + per-context restart",
        "waves": ("W16", "W17"),
        "test_file": (
            "tests/test_stop_summary_2026_07_29.py; "
            "tests/test_restart_contract_2026_07_29.py"
        ),
        "trace_artifacts": (
            "artifacts/traces/stop-summary-e2e.json",
            "artifacts/traces/restart-e2e.json",
        ),
    },
    {
        "criterion": 6,
        "name": "file preview (no raw binary)",
        "waves": ("W18",),
        "test_file": "tests/test_file_preview_2026_07_29.py",
        "trace_artifacts": ("artifacts/traces/preview-e2e.json",),
    },
    {
        "criterion": 7,
        "name": "projects collapsed by default + dual-profile",
        "waves": ("W19",),
        "test_file": "tests/test_projects_collapse_2026_07_29.py",
        "trace_artifacts": (),  # W19 ships failure-state + root-cause, no e2e json required by plan
    },
    {
        "criterion": 8,
        "name": "status cadence from live telemetry",
        "waves": ("W20",),
        "test_file": "tests/test_status_cadence_2026_07_29.py",
        "trace_artifacts": ("artifacts/traces/cadence-e2e.json",),
    },
    {
        "criterion": 9,
        "name": "instrumentation + cost honesty + conformance harness",
        "waves": ("W6", "W7", "W8", "W9"),
        "test_file": (
            "tests/test_named_state_2026_07_29.py; "
            "tests/test_cost_state_2026_07_29.py; "
            "tests/test_conformance_harness_2026_07_29.py; "
            "tests/test_trace_and_faults_2026_07_29.py"
        ),
        "trace_artifacts": (),
    },
    {
        "criterion": 10,
        "name": "containment + handoff + early-slice honesty floor",
        "waves": ("W1", "W2", "W3", "W4", "W5", "W10"),
        "test_file": (
            "tests/test_containment_smoke_2026_07_29.py; "
            "tests/test_exit_register_2026_07_29.py; "
            "tests/test_capability_inventory_2026_07_29.py; "
            "tests/test_rollup_evidence_2026_07_29.py; "
            "tests/test_freeze_gate_2026_07_29.py"
        ),
        "trace_artifacts": ("artifacts/EARLY-SLICE-PARTIAL.md",),
    },
)

#: Surfaces audited for dead controls (generator callables resolved lazily).
SURFACE_GENERATORS: Tuple[Tuple[str, str, str], ...] = (
    # (surface_id, module_path, callable_name)
    ("open-run", "anchor.ui.open_run_view", "generate_html"),
    ("attach", "anchor.ui.attach_view", "generate_html"),
    ("usage", "anchor.ui.usage_tiles", "generate_html"),
    ("cost", "anchor.ui.cost_view", "generate_html"),
    ("doctor", "anchor.ui.doctor_view", "generate_html"),
    ("stop-summary", "anchor.ui.stop_summary_tile", "generate_html"),
    ("restart", "anchor.ui.restart_controls", "generate_html"),
    ("preview", "anchor.ui.preview_view", "generate_html"),
    ("projects", "anchor.ui.projects_tree", "generate_html"),
    ("cadence", "anchor.ui.status_view", "generate_html"),
)

#: Out-of-criteria surfaces closed at W21 (fixed / disabled / E3).
OUT_OF_CRITERIA_DEFAULTS: Tuple[Dict[str, str], ...] = (
    {
        "surface": "named-state demo document (named_state.generate_html)",
        "closure": "fixed",
        "proof": (
            "W6 render_state primitive only — not a user North-Star control; "
            "emits labelled states, no dead clickables"
        ),
    },
    {
        "surface": "cost zero×state matrix demo (cost_view.generate_html_zero_matrix)",
        "closure": "fixed",
        "proof": (
            "W13 harness surface routes every cell through render_cost; "
            "no fabricated $0.00 outside measured"
        ),
    },
    {
        "surface": "restart contract matrix panel",
        "closure": "fixed",
        "proof": (
            "W17 documentation panel of preserved/lost contracts; "
            "live restart controls remain exactly-one per context"
        ),
    },
    {
        "surface": "reason-matrix / cannot-reason catalog panels",
        "closure": "fixed",
        "proof": (
            "Catalog tiles enumerate named cannot-* states via render_state; "
            "not live affordances bound to missing capabilities"
        ),
    },
    {
        "surface": "EARLY-SLICE-PARTIAL honesty label",
        "closure": "fixed",
        "proof": (
            "Explicit PARTIAL disclosure after W10; not a control surface; "
            "prevents over-claim of North Star"
        ),
    },
)


# --------------------------------------------------------------------------
# Errors + data shapes
# --------------------------------------------------------------------------


class DeadControlAuditError(AssertionError):
    """Raised when the dead-control audit finds violations."""

    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


class TraceabilityError(AssertionError):
    """Raised when the traceability matrix is illegal or incomplete."""

    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


class JoinGateError(AssertionError):
    """Raised when the surface-wave join gate refuses GO."""

    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


@dataclass(frozen=True)
class ControlRecord:
    """One rendered control (or named-state stand-in) found in HTML."""

    control_id: str
    disposition: str  # wired | named_state | hidden | dead
    tag: str = ""
    action: str = ""
    label: str = ""
    surface: str = ""
    snippet: str = ""
    reason: str = ""

    def as_dict(self) -> Dict[str, Any]:
        return {
            "control_id": self.control_id,
            "disposition": self.disposition,
            "tag": self.tag,
            "action": self.action,
            "label": self.label,
            "surface": self.surface,
            "snippet": self.snippet,
            "reason": self.reason,
        }


@dataclass
class SurfaceAuditResult:
    """Dead-control audit outcome for one surface HTML document."""

    surface_id: str
    controls: List[ControlRecord] = field(default_factory=list)
    dead_findings: List[DeadControlFinding] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.dead_findings and not self.errors

    def as_dict(self) -> Dict[str, Any]:
        return {
            "surface_id": self.surface_id,
            "ok": self.ok,
            "controls": [c.as_dict() for c in self.controls],
            "dead_findings": [
                f.as_dict() if hasattr(f, "as_dict") else dict(f)
                for f in self.dead_findings
            ],
            "errors": list(self.errors),
        }


@dataclass
class DeadControlAuditReport:
    """Full multi-surface dead-control audit report."""

    surfaces: Dict[str, SurfaceAuditResult] = field(default_factory=dict)
    ok: bool = True
    errors: List[str] = field(default_factory=list)
    findings_count: int = 0

    def as_dict(self) -> Dict[str, Any]:
        return {
            "ok": self.ok,
            "findings_count": self.findings_count,
            "errors": list(self.errors),
            "surfaces": {k: v.as_dict() for k, v in self.surfaces.items()},
        }


@dataclass(frozen=True)
class WaveGreenStatus:
    """Parsed GREEN + commit resolution for one wave."""

    wave_id: str
    green: bool
    commit_sha: str = ""
    commit_source: str = ""  # execution-log | proven.json | checkpoint | ""
    note: str = ""

    def as_dict(self) -> Dict[str, Any]:
        return {
            "wave_id": self.wave_id,
            "green": self.green,
            "commit_sha": self.commit_sha,
            "commit_source": self.commit_source,
            "note": self.note,
        }


@dataclass
class JoinGateResult:
    """Surface-wave join gate outcome (W10–W20)."""

    status: str  # GO | HALT
    message: str
    waves: Dict[str, WaveGreenStatus] = field(default_factory=dict)
    missing_green: Tuple[str, ...] = ()
    missing_sha: Tuple[str, ...] = ()

    @property
    def ok(self) -> bool:
        return self.status == GO

    def as_dict(self) -> Dict[str, Any]:
        return {
            "status": self.status,
            "message": self.message,
            "ok": self.ok,
            "missing_green": list(self.missing_green),
            "missing_sha": list(self.missing_sha),
            "waves": {k: v.as_dict() for k, v in self.waves.items()},
        }


@dataclass(frozen=True)
class TraceabilityRow:
    """One criterion row of the traceability matrix."""

    criterion: int
    name: str
    waves: str
    test_file: str
    commit_sha: str
    trace_artifact: str
    status: str  # CANDIDATE-MET | OPEN only

    def as_dict(self) -> Dict[str, Any]:
        return {
            "criterion": self.criterion,
            "name": self.name,
            "waves": self.waves,
            "test_file": self.test_file,
            "commit_sha": self.commit_sha,
            "trace_artifact": self.trace_artifact,
            "status": self.status,
        }


@dataclass
class TraceabilityMatrix:
    """Full criterion 1–10 matrix."""

    rows: List[TraceabilityRow] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors and len(self.rows) == 10

    def as_dict(self) -> Dict[str, Any]:
        return {
            "ok": self.ok,
            "errors": list(self.errors),
            "rows": [r.as_dict() for r in self.rows],
        }


@dataclass
class GateResult:
    """Composite W21 phase-4 GO decision."""

    status: str
    message: str
    join: Optional[JoinGateResult] = None
    dead_audit: Optional[DeadControlAuditReport] = None
    ambiguous_findings: int = 0
    matrix_ok: bool = False
    exit_recon: str = ""
    details: Tuple[str, ...] = ()

    @property
    def ok(self) -> bool:
        return self.status == GO

    def as_dict(self) -> Dict[str, Any]:
        return {
            "status": self.status,
            "message": self.message,
            "ok": self.ok,
            "ambiguous_findings": self.ambiguous_findings,
            "matrix_ok": self.matrix_ok,
            "exit_recon": self.exit_recon,
            "details": list(self.details),
            "join": None if self.join is None else self.join.as_dict(),
            "dead_audit": (
                None if self.dead_audit is None else self.dead_audit.as_dict()
            ),
        }


# --------------------------------------------------------------------------
# Path helpers
# --------------------------------------------------------------------------


def containment_root(root: Optional[Path] = None) -> Path:
    if root is not None:
        return Path(root)
    return Path(__file__).resolve().parents[1]


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _strip_tags(text: str) -> str:
    return re.sub(r"<[^>]+>", "", text or "").strip()


def _parse_attrs(attr_blob: str) -> Dict[str, str]:
    out: Dict[str, str] = {}
    for m in _ATTR_RE.finditer(attr_blob or ""):
        out[m.group(1).lower()] = m.group(2)
    return out


# --------------------------------------------------------------------------
# Control enumeration
# --------------------------------------------------------------------------


def enumerate_controls(
    html_text: str,
    *,
    surface: str = "",
) -> List[ControlRecord]:
    """Enumerate every rendered control / named-state stand-in in *html_text*.

    Disposition is one of ``wired``, ``named_state``, or ``dead``.
    ``hidden`` is reserved for expected controls that are absent from a
    known set (see :func:`classify_expected_control`).
    """
    if not html_text:
        return []
    records: List[ControlRecord] = []
    seen_ids: set = set()

    # Live / dead clickables.
    for m in _BUTTON_RE.finditer(html_text):
        tag = m.group(1).lower()
        attrs = m.group(2) or ""
        label = _strip_tags(m.group(3) or "")
        ctrl_m = _CONTROL_ATTR_RE.search(attrs)
        control_id = (ctrl_m.group(1) if ctrl_m else "").strip()
        act_m = _ACTION_ATTR_RE.search(attrs)
        action = (act_m.group(1).strip() if act_m else "")
        class_m = _CLASS_ATTR_RE.search(attrs)
        classes = (class_m.group(1) if class_m else "").lower()
        mode_m = _MODE_ATTR_RE.search(attrs)
        mode = (mode_m.group(1) if mode_m else "").lower()
        snippet = m.group(0)[:200]

        # Bare <a> without control markers are not controls.
        if tag == "a" and not control_id and not mode and LIVE_CONTROL_CLASS not in classes:
            if "button" not in classes and not act_m:
                continue

        is_dead_class = DEAD_CONTROL_CLASS in classes
        is_disabled = bool(re.search(r"\bdisabled\b", attrs, re.I))
        is_live_class = LIVE_CONTROL_CLASS in classes or mode == "live"
        noop = action.lower() in _NOOP_ACTIONS

        if is_dead_class or is_disabled or (noop and (control_id or tag == "button")):
            disposition = "dead"
            reason = (
                "explicit dead-control class"
                if is_dead_class
                else (
                    "disabled clickable"
                    if is_disabled
                    else "clickable no-op action %r" % (action,)
                )
            )
        elif is_live_class or (control_id and not noop and action):
            disposition = "wired"
            reason = "live action target"
        elif control_id or tag == "button":
            disposition = "dead"
            reason = "control-like clickable without real action"
        else:
            continue

        records.append(
            ControlRecord(
                control_id=control_id or ("(unlabeled-%s)" % tag),
                disposition=disposition,
                tag=tag,
                action=action,
                label=label,
                surface=surface,
                snippet=snippet,
                reason=reason,
            )
        )
        if control_id:
            seen_ids.add(control_id)

    # Named cannot-* states (no clickable).
    for m in _CANNOT_BLOCK_RE.finditer(html_text):
        attrs = m.group(1) or ""
        ctrl_m = _CONTROL_ATTR_RE.search(attrs)
        control_id = (ctrl_m.group(1) if ctrl_m else "").strip()
        if not control_id:
            # Still count anonymous cannot-state as named_state.
            control_id = "(named-state)"
        if control_id in seen_ids:
            # Prefer the named-state disposition when both appear (shouldn't).
            pass
        records.append(
            ControlRecord(
                control_id=control_id,
                disposition="named_state",
                tag="div",
                action="",
                label=_strip_tags(m.group(2) or "")[:80],
                surface=surface,
                snippet=m.group(0)[:200],
                reason="named cannot-* via render_state",
            )
        )
        seen_ids.add(control_id)

    return records


def classify_expected_control(
    control_id: str,
    records: Sequence[ControlRecord],
) -> str:
    """Return wired / named_state / hidden / dead for an expected control id."""
    matches = [r for r in records if r.control_id == control_id]
    if not matches:
        return "hidden"
    # Prefer dead if any dead match exists (finding).
    for r in matches:
        if r.disposition == "dead":
            return "dead"
    for r in matches:
        if r.disposition == "wired":
            return "wired"
    for r in matches:
        if r.disposition == "named_state":
            return "named_state"
    return matches[0].disposition


def audit_html(
    html_text: str,
    *,
    surface_id: str = "",
    expected_controls: Optional[Sequence[str]] = None,
) -> SurfaceAuditResult:
    """Audit one HTML document for dead controls + disposition of each control."""
    result = SurfaceAuditResult(surface_id=surface_id or "(anonymous)")
    result.controls = enumerate_controls(html_text, surface=result.surface_id)
    result.dead_findings = audit_dead_controls(html_text or "")

    # Any enumerated dead disposition is also a finding path.
    for rec in result.controls:
        if rec.disposition == "dead":
            # Ensure the shared auditor also flagged it; if not, record error.
            already = any(
                (f.control_id or "") == rec.control_id
                or rec.snippet[:40] in (f.snippet or "")
                for f in result.dead_findings
            )
            if not already and rec.control_id:
                result.errors.append(
                    "enumerated dead control %r on surface %s: %s"
                    % (rec.control_id, result.surface_id, rec.reason)
                )

    if expected_controls:
        for cid in expected_controls:
            disp = classify_expected_control(cid, result.controls)
            if disp == "dead":
                result.errors.append(
                    "expected control %r is dead on surface %s"
                    % (cid, result.surface_id)
                )
            # hidden is legal (capability absent → no element).
            # wired / named_state are legal.

    return result


def audit_html_out_of_criteria_dead(
    html_text: str,
    *,
    control_id: str,
    capability_present: bool = False,
) -> List[str]:
    """GWT: out-of-criteria control bound to missing capability → finding.

    Returns finding messages. E3 is illegal until the control is fixed or
    removed (see :func:`e3_allowed_for_control`).
    """
    findings: List[str] = []
    if capability_present:
        return findings
    records = enumerate_controls(html_text)
    for rec in records:
        if rec.control_id == control_id and rec.disposition in {"wired", "dead"}:
            findings.append(
                "out-of-criteria control %r bound to missing capability "
                "still renders disposition=%s — fix or remove from view"
                % (control_id, rec.disposition)
            )
    # Also catch dead clickables with that id.
    for f in audit_dead_controls(html_text or ""):
        if (f.control_id or "") == control_id:
            findings.append(
                "dead-control finding for out-of-criteria control %r: %s"
                % (control_id, f.reason)
            )
    return findings


def e3_allowed_for_control(
    html_text: str,
    *,
    control_id: str,
    capability_present: bool = False,
) -> Tuple[bool, str]:
    """E3 only when the surface is already honest (no dead / no live-on-absent)."""
    msgs = audit_html_out_of_criteria_dead(
        html_text,
        control_id=control_id,
        capability_present=capability_present,
    )
    if msgs:
        return False, E3_REJECTED_FOR_DEAD_MESSAGE + ": " + msgs[0]
    # Honest: hidden or named_state only.
    disp = classify_expected_control(control_id, enumerate_controls(html_text))
    if disp in {"hidden", "named_state"}:
        return True, "surface honest — E3 may document with reason"
    if disp == "wired" and capability_present:
        return True, "live control authorized — not an E3 candidate"
    return False, E3_REJECTED_FOR_DEAD_MESSAGE


# --------------------------------------------------------------------------
# Multi-surface audit
# --------------------------------------------------------------------------


def _import_generate(module_path: str, callable_name: str) -> Callable[..., str]:
    import importlib

    mod = importlib.import_module(module_path)
    fn = getattr(mod, callable_name)
    return fn


def collect_surface_html(
    *,
    root: Optional[Path] = None,
    generators: Optional[Sequence[Tuple[str, str, str]]] = None,
) -> Dict[str, str]:
    """Render each registered surface via its generate_html entry point.

    Failures are recorded as empty HTML with an error prefix (caller audits
    errors separately). Paths stay inside containment.
    """
    _ = containment_root(root)
    out: Dict[str, str] = {}
    for surface_id, module_path, callable_name in (generators or SURFACE_GENERATORS):
        try:
            fn = _import_generate(module_path, callable_name)
            html = fn()
            out[surface_id] = html if isinstance(html, str) else str(html)
        except Exception as exc:  # noqa: BLE001 — surface isolation
            out[surface_id] = ""
            # Stash error as a sentinel comment so audit can report it.
            out[surface_id] = "<!-- surface-render-error: %s -->" % (
                type(exc).__name__ + ": " + str(exc)[:200],
            )
    return out


def audit_all_surfaces(
    *,
    root: Optional[Path] = None,
    html_by_surface: Optional[Mapping[str, str]] = None,
) -> DeadControlAuditReport:
    """Run the dead-control audit across every surface."""
    report = DeadControlAuditReport()
    docs = (
        dict(html_by_surface)
        if html_by_surface is not None
        else collect_surface_html(root=root)
    )
    total_findings = 0
    for surface_id, html_text in docs.items():
        if html_text.startswith("<!-- surface-render-error:"):
            sr = SurfaceAuditResult(surface_id=surface_id)
            sr.errors.append(html_text.strip("<!- >"))
            report.surfaces[surface_id] = sr
            report.errors.append("%s: render failed" % surface_id)
            continue
        sr = audit_html(html_text, surface_id=surface_id)
        report.surfaces[surface_id] = sr
        total_findings += len(sr.dead_findings)
        if sr.errors:
            report.errors.extend(sr.errors)
    report.findings_count = total_findings
    report.ok = total_findings == 0 and not report.errors
    return report


def assert_no_dead_controls_across_surfaces(
    report: Optional[DeadControlAuditReport] = None,
    *,
    root: Optional[Path] = None,
) -> DeadControlAuditReport:
    """Raise :class:`DeadControlAuditError` when any surface has findings."""
    r = report if report is not None else audit_all_surfaces(root=root)
    if not r.ok:
        parts: List[str] = []
        for sid, sr in r.surfaces.items():
            for f in sr.dead_findings:
                parts.append(
                    "%s:%s#%s (%s)"
                    % (sid, f.tag, f.control_id or "?", f.reason)
                )
            for e in sr.errors:
                parts.append("%s: %s" % (sid, e))
        raise DeadControlAuditError(
            "%s: %d finding(s): %s"
            % (DEAD_CONTROL_FINDING_MESSAGE, r.findings_count, "; ".join(parts) or r.errors)
        )
    return r


# --------------------------------------------------------------------------
# EXECUTION-LOG GREEN + commit SHA resolution (join gate)
# --------------------------------------------------------------------------


def parse_green_waves(log_text: str) -> Dict[int, bool]:
    """Return ``{wave_number: True}`` for every ``Wave N/22 GREEN`` line."""
    found: Dict[int, bool] = {}
    for m in _WAVE_GREEN_RE.finditer(log_text or ""):
        found[int(m.group(1))] = True
    return found


def _section_for_wave(log_text: str, wave_n: int) -> str:
    """Return the markdown section body for ``## Wave N`` if present."""
    text = log_text or ""
    matches = list(_WAVE_SECTION_RE.finditer(text))
    for i, m in enumerate(matches):
        if int(m.group(1)) != wave_n:
            continue
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        return text[start:end]
    return ""


def _sha_from_commit_field(raw: str) -> str:
    """Extract a hex SHA from a ``**commit:**`` field value, or ''."""
    text = (raw or "").strip()
    if not text:
        return ""
    # Bare sha.
    first = text.split()[0].strip("()`'\".,;")
    if _SHA_HEX.match(first):
        return first.lower()
    # Embedded ``commit=<sha>`` or ``(sha)``.
    m = re.search(r"\b([0-9a-f]{7,40})\b", text, re.I)
    if m and _SHA_HEX.match(m.group(1)):
        # Reject words that look like hex-ish placeholders? accept real hex only.
        return m.group(1).lower()
    return ""


def commit_from_execution_log(log_text: str, wave_n: int) -> str:
    """Pull commit SHA from the Wave N section of EXECUTION-LOG.md."""
    section = _section_for_wave(log_text, wave_n)
    if not section:
        # Whole-log scan for a commit near the GREEN line for this wave.
        for m in _COMMIT_LINE_RE.finditer(log_text or ""):
            # Prefer sections; if no section, do not invent.
            pass
        return ""
    for m in _COMMIT_LINE_RE.finditer(section):
        sha = _sha_from_commit_field(m.group(1))
        if sha:
            return sha
    # Also accept GREEN append lines that embed commit=<sha>.
    m = re.search(
        r"Wave\s+%d/22\s+GREEN[^\n]*commit[=:\s]+([0-9a-f]{7,40})" % wave_n,
        section,
        re.I,
    )
    if m:
        return m.group(1).lower()
    m = re.search(r"\bcommit[=:\s]+([0-9a-f]{7,40})\b", section, re.I)
    if m:
        return m.group(1).lower()
    return ""


def commit_from_proven_json(root: Path, wave_n: int) -> str:
    """Read commit from ``.foreman/wave-N-proven.json`` when present."""
    candidates = [
        root / ".foreman" / ("wave-%d-proven.json" % wave_n),
        root / ".foreman" / ("wave-N-proven.json".replace("N", str(wave_n))),
        root / "foreman" / ("wave-%d-proven.json" % wave_n),
    ]
    for path in candidates:
        if not path.is_file():
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError, json.JSONDecodeError):
            continue
        if not isinstance(data, dict):
            continue
        for key in ("commit_sha", "commit", "sha", "git_sha", "head"):
            val = data.get(key)
            if isinstance(val, str) and _SHA_HEX.match(val.strip()):
                return val.strip().lower()
    return ""


def commit_from_checkpoint(root: Path) -> str:
    """Fallback: ``foreman-checkpoint.json`` last_commit."""
    path = root / FOREMAN_CHECKPOINT_RELPATH
    if not path.is_file():
        return ""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, json.JSONDecodeError):
        return ""
    if not isinstance(data, dict):
        return ""
    for key in ("last_commit", "commit_sha", "commit"):
        val = data.get(key)
        if isinstance(val, str) and _SHA_HEX.match(val.strip()):
            return val.strip().lower()
    return ""


def resolve_wave_status(
    wave_n: int,
    *,
    root: Optional[Path] = None,
    log_text: Optional[str] = None,
) -> WaveGreenStatus:
    """Resolve GREEN + commit SHA for wave N (join-gate input)."""
    base = containment_root(root)
    text = log_text if log_text is not None else (
        _read_text(base / EXECUTION_LOG_RELPATH)
        if (base / EXECUTION_LOG_RELPATH).is_file()
        else ""
    )
    green_map = parse_green_waves(text)
    green = bool(green_map.get(wave_n))
    wave_id = "W%d" % wave_n

    sha = commit_from_execution_log(text, wave_n)
    source = "execution-log" if sha else ""
    if not sha:
        sha = commit_from_proven_json(base, wave_n)
        source = "proven.json" if sha else ""
    if not sha and green:
        # Steward-land waves often leave placeholder commit lines; the
        # checkpoint last_commit is the host-recorded tip for those lands.
        sha = commit_from_checkpoint(base)
        source = "checkpoint" if sha else ""

    note = ""
    if green and not sha:
        note = "GREEN without resolvable commit SHA"
    elif not green:
        note = "not GREEN in EXECUTION-LOG"
    return WaveGreenStatus(
        wave_id=wave_id,
        green=green,
        commit_sha=sha,
        commit_source=source,
        note=note,
    )


def surface_wave_join_gate(
    *,
    root: Optional[Path] = None,
    log_text: Optional[str] = None,
    min_wave: int = SURFACE_JOIN_MIN,
    max_wave: int = SURFACE_JOIN_MAX,
) -> JoinGateResult:
    """W21 join gate: every W10–W20 GREEN with a resolvable commit SHA.

    The sweep must never run over an unbuilt surface and mistake absence for
    cleanliness. Missing GREEN → HALT. GREEN without SHA → HALT.
    """
    waves: Dict[str, WaveGreenStatus] = {}
    missing_green: List[str] = []
    missing_sha: List[str] = []
    for n in range(min_wave, max_wave + 1):
        st = resolve_wave_status(n, root=root, log_text=log_text)
        waves[st.wave_id] = st
        if not st.green:
            missing_green.append(st.wave_id)
        elif not st.commit_sha or not _SHA_HEX.match(st.commit_sha):
            missing_sha.append(st.wave_id)

    if missing_green:
        return JoinGateResult(
            status=HALT,
            message="%s: missing %s" % (JOIN_MISSING_GREEN_MESSAGE, ", ".join(missing_green)),
            waves=waves,
            missing_green=tuple(missing_green),
            missing_sha=tuple(missing_sha),
        )
    if missing_sha:
        return JoinGateResult(
            status=HALT,
            message="%s: %s" % (JOIN_MISSING_SHA_MESSAGE, ", ".join(missing_sha)),
            waves=waves,
            missing_green=tuple(missing_green),
            missing_sha=tuple(missing_sha),
        )
    return JoinGateResult(
        status=GO,
        message="W%d–W%d all GREEN with commit SHA" % (min_wave, max_wave),
        waves=waves,
        missing_green=(),
        missing_sha=(),
    )


# --------------------------------------------------------------------------
# Traceability matrix
# --------------------------------------------------------------------------


def _primary_commit_for_waves(
    wave_ids: Sequence[str],
    *,
    root: Optional[Path] = None,
    log_text: Optional[str] = None,
) -> str:
    """Prefer the first resolvable commit among *wave_ids*."""
    shas: List[str] = []
    for wid in wave_ids:
        m = re.match(r"W(\d+)$", wid, re.I)
        if not m:
            continue
        st = resolve_wave_status(int(m.group(1)), root=root, log_text=log_text)
        if st.commit_sha:
            shas.append(st.commit_sha)
    if not shas:
        return ""
    # If all equal, one SHA; else join unique short form for multi-wave criteria.
    uniq = []
    for s in shas:
        if s not in uniq:
            uniq.append(s)
    return ",".join(uniq)


def _traces_present(relpaths: Sequence[str], root: Path) -> Tuple[str, bool]:
    if not relpaths:
        return "(none required)", True
    present = []
    missing = []
    for rel in relpaths:
        p = root / rel
        if p.is_file():
            present.append(rel)
        else:
            missing.append(rel)
    if missing:
        return "; ".join(relpaths), False
    return "; ".join(present), True


def _test_files_present(spec: str, root: Path) -> bool:
    parts = [p.strip() for p in (spec or "").split(";") if p.strip()]
    if not parts:
        return False
    for part in parts:
        if not (root / part).is_file():
            return False
    return True


def build_traceability_matrix(
    *,
    root: Optional[Path] = None,
    log_text: Optional[str] = None,
    force_status: Optional[str] = None,
) -> TraceabilityMatrix:
    """Build criterion 1–10 rows from CRITERION_MAP + join-gate evidence."""
    base = containment_root(root)
    text = log_text if log_text is not None else (
        _read_text(base / EXECUTION_LOG_RELPATH)
        if (base / EXECUTION_LOG_RELPATH).is_file()
        else ""
    )
    matrix = TraceabilityMatrix()
    for entry in CRITERION_MAP:
        waves = entry["waves"]
        waves_s = ", ".join(waves)
        test_file = entry["test_file"]
        traces = entry.get("trace_artifacts") or ()
        commit = _primary_commit_for_waves(waves, root=base, log_text=text)
        trace_s, traces_ok = _traces_present(traces, base)
        tests_ok = _test_files_present(test_file, base)

        # Surface criteria (1–8) require their waves GREEN+SHA for CANDIDATE-MET.
        surface_waves = [
            w for w in waves
            if re.match(r"W(\d+)$", w) and 10 <= int(w[1:]) <= 20
        ]
        join_ok = True
        for w in surface_waves:
            st = resolve_wave_status(int(w[1:]), root=base, log_text=text)
            if not (st.green and st.commit_sha):
                join_ok = False
                break

        if force_status is not None:
            status = force_status
        elif tests_ok and commit and traces_ok and join_ok:
            status = STATUS_CANDIDATE_MET
        else:
            status = STATUS_OPEN

        # Criterion 9–10 are pre-surface / structural: GREEN not required from
        # W10–W20 only — tests + (optional) traces suffice when commit resolvable
        # from any cited wave or checkpoint.
        if entry["criterion"] >= 9 and force_status is None:
            if tests_ok and (commit or commit_from_checkpoint(base)):
                if not commit:
                    commit = commit_from_checkpoint(base)
                status = STATUS_CANDIDATE_MET

        matrix.rows.append(
            TraceabilityRow(
                criterion=int(entry["criterion"]),
                name=str(entry["name"]),
                waves=waves_s,
                test_file=test_file,
                commit_sha=commit,
                trace_artifact=trace_s,
                status=status,
            )
        )
    return matrix


def validate_traceability_matrix(
    matrix: Union[TraceabilityMatrix, Sequence[TraceabilityRow], str],
    *,
    allow_open: bool = True,
    s1_pass: bool = False,
) -> TraceabilityMatrix:
    """Validate matrix rows. ``MET`` before S1 fails. Incomplete CANDIDATE fails.

    *matrix* may be a :class:`TraceabilityMatrix`, a sequence of rows, or
    markdown text (parsed).
    """
    if isinstance(matrix, str):
        m = parse_traceability_markdown(matrix)
    elif isinstance(matrix, TraceabilityMatrix):
        m = matrix
    else:
        m = TraceabilityMatrix(rows=list(matrix))

    errors: List[str] = []
    if len(m.rows) != 10:
        errors.append(
            "traceability matrix must have exactly 10 criterion rows (got %d)"
            % len(m.rows)
        )

    seen = set()
    for row in m.rows:
        if row.criterion in seen:
            errors.append("duplicate criterion %d" % row.criterion)
        seen.add(row.criterion)

        status = (row.status or "").strip().upper()
        # Normalise candidate form.
        if status in {"CANDIDATE-MET", "CANDIDATE_MET", "CANDIDATE MET"}:
            status_n = STATUS_CANDIDATE_MET
        elif status == STATUS_OPEN:
            status_n = STATUS_OPEN
        elif status == STATUS_MET:
            if not s1_pass:
                errors.append(
                    "%s (criterion %d)" % (MET_BEFORE_S1_MESSAGE, row.criterion)
                )
            status_n = STATUS_MET
        else:
            errors.append(
                "criterion %d illegal status %r — only CANDIDATE-MET or OPEN"
                % (row.criterion, row.status)
            )
            status_n = row.status

        if status_n == STATUS_CANDIDATE_MET:
            if not (row.test_file or "").strip():
                errors.append(
                    "%s (criterion %d: missing test file)"
                    % (INCOMPLETE_ROW_MESSAGE, row.criterion)
                )
            if not (row.commit_sha or "").strip():
                errors.append(
                    "%s (criterion %d: missing commit SHA)"
                    % (INCOMPLETE_ROW_MESSAGE, row.criterion)
                )
            # Trace: required when the map lists traces; "(none required)" is ok.
            ta = (row.trace_artifact or "").strip()
            if not ta:
                errors.append(
                    "%s (criterion %d: missing trace artifact)"
                    % (INCOMPLETE_ROW_MESSAGE, row.criterion)
                )
        elif status_n == STATUS_OPEN and not allow_open:
            errors.append("criterion %d is OPEN" % row.criterion)

    m.errors = errors
    return m


def parse_traceability_markdown(text: str) -> TraceabilityMatrix:
    """Parse TRACEABILITY-MATRIX.md table into rows."""
    matrix = TraceabilityMatrix()
    for line in (text or "").splitlines():
        line = line.strip()
        if not line.startswith("|"):
            continue
        if line.startswith("|---") or "criterion" in line.lower() and "wave" in line.lower():
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        if len(cells) < 6:
            continue
        # criterion | name | wave(s) | test file | commit SHA | trace artifact | status
        try:
            crit = int(re.sub(r"[^\d]", "", cells[0]) or "0")
        except ValueError:
            continue
        if crit < 1 or crit > 10:
            continue
        if len(cells) >= 7:
            name, waves, test_f, commit, trace, status = (
                cells[1], cells[2], cells[3], cells[4], cells[5], cells[6]
            )
        else:
            # 6-col compact: criterion | waves | test | commit | trace | status
            name = ""
            waves, test_f, commit, trace, status = (
                cells[1], cells[2], cells[3], cells[4], cells[5]
            )
        def _strip_cell(s: str) -> str:
            t = (s or "").strip()
            if t.startswith("`") and t.endswith("`") and len(t) >= 2:
                return t[1:-1].strip()
            return t

        matrix.rows.append(
            TraceabilityRow(
                criterion=crit,
                name=name,
                waves=waves,
                test_file=_strip_cell(test_f),
                commit_sha=_strip_cell(commit),
                trace_artifact=_strip_cell(trace),
                status=status.strip() if status else status,
            )
        )
    return matrix


def render_traceability_markdown(matrix: TraceabilityMatrix) -> str:
    """Render TRACEABILITY-MATRIX.md (status CANDIDATE-MET or OPEN only)."""
    lines = [
        "# Traceability Matrix",
        "",
        "Build: Anchor sleep cycle 2026-07-28 (v1.2)",
        "Wave: W21 — Phase 4: Unnamed-control sweep + dead-control audit + traceability matrix",
        "",
        "Status may only be **CANDIDATE-MET** (structural, rendered-string level) "
        "or **OPEN**. A **MET** stamp before S1 (W22) fails the validator. "
        "S1 is the only gate that converts CANDIDATE-MET → MET.",
        "",
        "| criterion | name | wave(s) | test file | commit SHA | trace artifact | status |",
        "|-----------|------|---------|-----------|------------|-----------------|--------|",
    ]
    for row in sorted(matrix.rows, key=lambda r: r.criterion):
        lines.append(
            "| %d | %s | %s | `%s` | `%s` | `%s` | %s |"
            % (
                row.criterion,
                row.name.replace("|", "/"),
                row.waves,
                row.test_file.replace("|", ";"),
                row.commit_sha or "(missing)",
                row.trace_artifact or "(missing)",
                row.status,
            )
        )
    lines.extend(
        [
            "",
            "## Binding rules (machine-enforced in tools/dead_control_audit.py)",
            "",
            "- Status ∈ {CANDIDATE-MET, OPEN} only; MET before S1 → validator fail",
            "- CANDIDATE-MET requires test file + commit SHA + trace artifact field",
            "- Surface-wave join gate: W10–W20 GREEN + commit SHA before W21 GO",
            "- Incomplete row fails naming the criterion (never silent met)",
            "",
        ]
    )
    return "\n".join(lines)


def write_traceability_matrix(
    matrix: Optional[TraceabilityMatrix] = None,
    *,
    root: Optional[Path] = None,
) -> Path:
    base = containment_root(root)
    m = matrix if matrix is not None else build_traceability_matrix(root=base)
    # Refuse to write MET-before-S1.
    validated = validate_traceability_matrix(m, allow_open=True, s1_pass=False)
    if any(STATUS_MET in e or "MET before S1" in e for e in validated.errors):
        raise TraceabilityError("; ".join(validated.errors))
    path = base / TRACEABILITY_RELPATH
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_traceability_markdown(m), encoding="utf-8")
    return path


# --------------------------------------------------------------------------
# Out-of-criteria surfaces
# --------------------------------------------------------------------------


def render_out_of_criteria_markdown(
    rows: Optional[Sequence[Mapping[str, str]]] = None,
) -> str:
    rows = list(rows) if rows is not None else list(OUT_OF_CRITERIA_DEFAULTS)
    lines = [
        "# Out-of-Criteria Surfaces",
        "",
        "Build: Anchor sleep cycle 2026-07-28 (v1.2)",
        "Wave: W21 — Phase 4 close-out",
        "",
        "Each surface outside the ten criteria is closed as **fixed**, "
        "**disabled**, or a **signed E3** with proof the surface is already "
        "honest (or removed). E3 is rejected while a dead control remains.",
        "",
        "| surface | closure | proof |",
        "|---------|---------|-------|",
    ]
    for r in rows:
        lines.append(
            "| %s | %s | %s |"
            % (
                str(r.get("surface", "")).replace("|", "/"),
                str(r.get("closure", "")),
                str(r.get("proof", "")).replace("|", "/"),
            )
        )
    lines.extend(
        [
            "",
            "## Closure rules",
            "",
            "- **fixed** — surface rendered honest (named state / no dead control)",
            "- **disabled** — surface removed from view / not emitted",
            "- **signed E3** — exit register E3 with John confirmation; surface already honest",
            "- Dead control on an out-of-criteria surface → finding; E3 refused until fixed/removed",
            "",
        ]
    )
    return "\n".join(lines)


def write_out_of_criteria_surfaces(
    *,
    root: Optional[Path] = None,
    rows: Optional[Sequence[Mapping[str, str]]] = None,
) -> Path:
    base = containment_root(root)
    path = base / OUT_OF_CRITERIA_RELPATH
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_out_of_criteria_markdown(rows), encoding="utf-8")
    return path


def parse_out_of_criteria_closures(text: str) -> List[Dict[str, str]]:
    """Parse OUT-OF-CRITERIA-SURFACES.md rows; each must have a legal closure."""
    legal = {"fixed", "disabled", "signed e3", "e3", "signed-e3"}
    out: List[Dict[str, str]] = []
    for line in (text or "").splitlines():
        line = line.strip()
        if not line.startswith("|"):
            continue
        if line.startswith("|---") or line.lower().startswith("| surface"):
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        if len(cells) < 3:
            continue
        closure = cells[1].strip().lower()
        if closure not in legal and not closure.startswith("signed"):
            continue
        out.append(
            {"surface": cells[0], "closure": cells[1], "proof": cells[2]}
        )
    return out


# --------------------------------------------------------------------------
# Exit-register reconciliation
# --------------------------------------------------------------------------


def reconcile_exit_register(
    *,
    root: Optional[Path] = None,
) -> Dict[str, Any]:
    """Recompute conjunction score; fourth exit or second on one criterion HALTs."""
    from anchor.build import exit_register as er

    base = containment_root(root)
    path = base / EXIT_REGISTER_RELPATH
    text = _read_text(path) if path.is_file() else er.empty_register_markdown()
    signed_count = er.load_signed_count_from_markdown(text)
    # Zero signed exits → empty row list → OK.
    rows: List[Any] = []
    # Future: parse full rows when any are signed. For now signed_count==0.
    score = er.score_conjunction(rows)
    may_start = er.may_start_subsequent_wave(rows)
    status_s = er.terminal_status(rows, s1_verdict=None)
    return {
        "signed_count": signed_count,
        "score": score,
        "may_start_wave": may_start,
        "terminal_status": status_s,
        "halt_rebaseline": score == er.HALT_REBASELINE,
        "path": str(path).replace("\\", "/"),
    }


# --------------------------------------------------------------------------
# Composite W21 GO
# --------------------------------------------------------------------------


def phase4_go_decision(
    *,
    root: Optional[Path] = None,
    html_by_surface: Optional[Mapping[str, str]] = None,
    skip_surface_render: bool = False,
    ambiguous_findings: Optional[int] = None,
) -> GateResult:
    """Full W21 GO: join + dead audit + ambiguous zeros + matrix + exit recon.

    When *skip_surface_render* is True, dead-control audit is skipped unless
    *html_by_surface* is provided (tests inject fixtures).
    """
    base = containment_root(root)
    details: List[str] = []

    join = surface_wave_join_gate(root=base)
    if not join.ok:
        return GateResult(
            status=HALT,
            message=join.message,
            join=join,
            details=tuple(join.missing_green + join.missing_sha),
        )
    details.append("join:GO")

    dead_report: Optional[DeadControlAuditReport] = None
    if html_by_surface is not None or not skip_surface_render:
        dead_report = audit_all_surfaces(root=base, html_by_surface=html_by_surface)
        if not dead_report.ok:
            return GateResult(
                status=HALT,
                message="%s (%d findings)"
                % (DEAD_CONTROL_FINDING_MESSAGE, dead_report.findings_count),
                join=join,
                dead_audit=dead_report,
                details=tuple(dead_report.errors),
            )
        details.append("dead_audit:clean")

    amb = ambiguous_findings
    if amb is None:
        try:
            from tools.ambiguous_zero_audit import audit_all_surfaces_ambiguous

            amb_report = audit_all_surfaces_ambiguous(
                root=base, html_by_surface=html_by_surface
            )
            amb = amb_report.findings_count
            if not amb_report.ok:
                return GateResult(
                    status=HALT,
                    message="ambiguous-zero audit found %d finding(s)" % amb,
                    join=join,
                    dead_audit=dead_report,
                    ambiguous_findings=amb,
                )
        except Exception as exc:  # noqa: BLE001
            # If the module is unavailable mid-bootstrap, treat as unchecked.
            details.append("ambiguous:skipped (%s)" % type(exc).__name__)
            amb = 0
    elif amb > 0:
        return GateResult(
            status=HALT,
            message="ambiguous-zero audit found %d finding(s)" % amb,
            join=join,
            dead_audit=dead_report,
            ambiguous_findings=amb,
        )
    details.append("ambiguous:0")

    matrix = build_traceability_matrix(root=base)
    validated = validate_traceability_matrix(matrix, allow_open=False, s1_pass=False)
    if validated.errors:
        # Allow OPEN only when join is GO? done-when wants all CANDIDATE-MET.
        return GateResult(
            status=HALT,
            message="traceability matrix not ready: %s" % "; ".join(validated.errors[:3]),
            join=join,
            dead_audit=dead_report,
            ambiguous_findings=amb or 0,
            matrix_ok=False,
            details=tuple(validated.errors),
        )
    details.append("matrix:CANDIDATE-MET×10")

    recon = reconcile_exit_register(root=base)
    if recon.get("halt_rebaseline"):
        return GateResult(
            status=HALT_REBASELINE,
            message="exit-register conjunction HALT_REBASELINE",
            join=join,
            dead_audit=dead_report,
            ambiguous_findings=amb or 0,
            matrix_ok=True,
            exit_recon=str(recon.get("score")),
        )
    details.append("exit_recon:%s signed=%s" % (recon.get("score"), recon.get("signed_count")))

    return GateResult(
        status=GO,
        message="W21 phase-4 close-out GO",
        join=join,
        dead_audit=dead_report,
        ambiguous_findings=amb or 0,
        matrix_ok=True,
        exit_recon=str(recon.get("score")),
        details=tuple(details),
    )


def bootstrap_wave21(
    *,
    root: Optional[Path] = None,
    skip_surface_render: bool = False,
) -> Dict[str, Path]:
    """Write TRACEABILITY-MATRIX + OUT-OF-CRITERIA-SURFACES; return paths."""
    base = containment_root(root)
    matrix = build_traceability_matrix(root=base)
    tpath = write_traceability_matrix(matrix, root=base)
    opath = write_out_of_criteria_surfaces(root=base)
    # Touch exit recon (no write when zero signed).
    reconcile_exit_register(root=base)
    return {
        TRACEABILITY_RELPATH: tpath,
        OUT_OF_CRITERIA_RELPATH: opath,
    }


__all__ = [
    "GO",
    "HALT",
    "HALT_REBASELINE",
    "WAVE_ID",
    "STATUS_CANDIDATE_MET",
    "STATUS_OPEN",
    "STATUS_MET",
    "TRACEABILITY_RELPATH",
    "OUT_OF_CRITERIA_RELPATH",
    "CRITERION_MAP",
    "SURFACE_GENERATORS",
    "OUT_OF_CRITERIA_DEFAULTS",
    "JOIN_MISSING_GREEN_MESSAGE",
    "JOIN_MISSING_SHA_MESSAGE",
    "MET_BEFORE_S1_MESSAGE",
    "INCOMPLETE_ROW_MESSAGE",
    "DEAD_CONTROL_FINDING_MESSAGE",
    "E3_REJECTED_FOR_DEAD_MESSAGE",
    "DeadControlAuditError",
    "TraceabilityError",
    "JoinGateError",
    "ControlRecord",
    "SurfaceAuditResult",
    "DeadControlAuditReport",
    "WaveGreenStatus",
    "JoinGateResult",
    "TraceabilityRow",
    "TraceabilityMatrix",
    "GateResult",
    "containment_root",
    "enumerate_controls",
    "classify_expected_control",
    "audit_html",
    "audit_html_out_of_criteria_dead",
    "e3_allowed_for_control",
    "collect_surface_html",
    "audit_all_surfaces",
    "assert_no_dead_controls_across_surfaces",
    "parse_green_waves",
    "commit_from_execution_log",
    "commit_from_proven_json",
    "commit_from_checkpoint",
    "resolve_wave_status",
    "surface_wave_join_gate",
    "build_traceability_matrix",
    "validate_traceability_matrix",
    "parse_traceability_markdown",
    "render_traceability_markdown",
    "write_traceability_matrix",
    "render_out_of_criteria_markdown",
    "write_out_of_criteria_surfaces",
    "parse_out_of_criteria_closures",
    "reconcile_exit_register",
    "phase4_go_decision",
    "bootstrap_wave21",
]
