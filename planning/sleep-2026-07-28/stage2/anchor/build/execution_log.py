"""EXECUTION-LOG append schema — W9, Phase 2.

Machine schema for one appended row per wave. Required fields:

* ``wave_id``
* ``commit_sha`` (present — a GREEN row without a commit SHA is not GO)
* ``gate_command``
* ``attestation_source`` — **orchestrator-written only** (host counts as the
  host-compute path the orchestrator uses; sub-agent is rejected)
* ``exit_register_delta`` — what changed in the exit register this wave

Hard rules (frozen plan GWTs):

* A **surface wave** reporting GREEN with no end-to-end trace artifact is
  rejected citing ``no end-to-end trace`` and the wave is not GO.
* Attestation source must be orchestrator/host; a sub-agent-authored source
  is refused and does not count.
* Only the orchestrator (or host path it drives) may append GO rows.

Paths are relative to the stage2 containment root (or an injected ``root``).
No absolute host paths are hard-coded.
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple, Union

from tools.attestation import (
    EVIDENCE_SOURCES,
    SOURCE_HOST,
    SOURCE_ORCHESTRATOR,
    SOURCE_SUB_AGENT,
    is_evidence_source,
    normalize_source,
)

# Lazy import of trace helpers so unit tests can monkeypatch freely and so
# a missing traces dir is a clean reject rather than an import-time crash.
from anchor.build import trace_artifact as _trace_mod

# --------------------------------------------------------------------------
# Public constants
# --------------------------------------------------------------------------

GO = "GO"
NOT_GO = "NOT_GO"
HALT = "HALT"

#: Relative path of the execution log under the containment root.
EXECUTION_LOG_RELPATH = "EXECUTION-LOG.md"

#: Schema id stamped on validated rows.
EXECUTION_LOG_SCHEMA = "execution-log-row/v1"

#: Verbatim reject phrase for GREEN surface waves without a trace (GWT).
NO_E2E_TRACE_MESSAGE = "no end-to-end trace"

#: Attestation sources allowed to write a countable EXECUTION-LOG row.
ALLOWED_ATTESTATION_SOURCES: frozenset = frozenset(
    {SOURCE_ORCHESTRATOR, SOURCE_HOST, "orchestrator-written"}
)

#: Surface waves (W10–W21) require an e2e trace for GREEN. Phase-0/1/2
#: primitive waves (W1–W9) and S1 (W22) do not use this surface rule.
SURFACE_WAVE_MIN = 10
SURFACE_WAVE_MAX = 21

_WAVE_ID = re.compile(r"^W(\d{1,2})$", re.IGNORECASE)
_SHA_HEX = re.compile(r"^[0-9a-f]{7,40}$", re.IGNORECASE)


# --------------------------------------------------------------------------
# Errors
# --------------------------------------------------------------------------


class ExecutionLogError(Exception):
    """Raised when an EXECUTION-LOG row fails schema / GO rules."""

    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


class NoEndToEndTrace(ExecutionLogError):
    """Surface GREEN without a schema-valid end-to-end trace artifact."""


class IllegalAttestationSource(ExecutionLogError):
    """Attestation source is not orchestrator/host."""


class MissingCommitSha(ExecutionLogError):
    """Commit SHA is required on every appendable row."""


# --------------------------------------------------------------------------
# Row schema
# --------------------------------------------------------------------------


@dataclass
class ExecutionLogRow:
    """One EXECUTION-LOG append row (validated schema)."""

    wave_id: str
    commit_sha: str
    gate_command: str
    attestation_source: str
    exit_register_delta: Dict[str, Any]
    status: str = GO
    trace_relpath: str = ""
    as_of: str = ""
    note: str = ""
    schema: str = EXECUTION_LOG_SCHEMA
    pass_count: Optional[int] = None
    fail_count: Optional[int] = None

    def as_dict(self) -> Dict[str, Any]:
        return {
            "schema": self.schema,
            "wave_id": self.wave_id,
            "commit_sha": self.commit_sha,
            "gate_command": self.gate_command,
            "attestation_source": self.attestation_source,
            "exit_register_delta": dict(self.exit_register_delta),
            "status": self.status,
            "trace_relpath": self.trace_relpath,
            "as_of": self.as_of,
            "note": self.note,
            "pass_count": self.pass_count,
            "fail_count": self.fail_count,
        }


@dataclass
class AppendResult:
    """Outcome of an append attempt."""

    ok: bool
    go: bool
    row: Optional[ExecutionLogRow] = None
    message: str = ""
    written_path: Optional[str] = None  # relative when written

    def as_dict(self) -> Dict[str, Any]:
        return {
            "ok": self.ok,
            "go": self.go,
            "message": self.message,
            "written_path": self.written_path,
            "row": None if self.row is None else self.row.as_dict(),
        }


# --------------------------------------------------------------------------
# Wave classification
# --------------------------------------------------------------------------


def parse_wave_number(wave_id: str) -> Optional[int]:
    """Return the integer N from ``W<N>``, or None when the id is malformed."""
    if not wave_id:
        return None
    m = _WAVE_ID.match(str(wave_id).strip())
    if not m:
        return None
    return int(m.group(1))


def is_surface_wave(wave_id: str) -> bool:
    """True for W10–W21 — the waves that require e2e traces for GREEN."""
    n = parse_wave_number(wave_id)
    if n is None:
        return False
    return SURFACE_WAVE_MIN <= n <= SURFACE_WAVE_MAX


# --------------------------------------------------------------------------
# Validation
# --------------------------------------------------------------------------


def validate_row(
    row: Union[ExecutionLogRow, Mapping[str, Any]],
    *,
    root: Optional[Path] = None,
    require_trace_for_surface_green: bool = True,
    trace_artifact: Optional[Any] = None,
) -> ExecutionLogRow:
    """Validate an EXECUTION-LOG row against the W9 schema.

    Raises :class:`ExecutionLogError` (or a subclass) on failure. A surface
    wave reporting GREEN with no end-to-end trace raises
    :class:`NoEndToEndTrace` citing ``no end-to-end trace``.
    """
    r = row if isinstance(row, ExecutionLogRow) else _row_from_mapping(row)

    if not r.wave_id or not str(r.wave_id).strip():
        raise ExecutionLogError("wave_id is required")
    if parse_wave_number(r.wave_id) is None:
        raise ExecutionLogError(
            "wave_id must look like W<n> (e.g. W10); got %r" % (r.wave_id,)
        )

    if not r.commit_sha or not str(r.commit_sha).strip():
        raise MissingCommitSha(
            "commit SHA is required — a GREEN row without commit SHA is not GO"
        )
    sha = str(r.commit_sha).strip()
    if not _SHA_HEX.match(sha):
        raise MissingCommitSha(
            "commit SHA must be a git hex digest (7–40 chars); got %r" % (sha,)
        )
    r.commit_sha = sha.lower()

    if not r.gate_command or not str(r.gate_command).strip():
        raise ExecutionLogError("gate-command is required")

    src = normalize_source(r.attestation_source)
    # Plan: attestation source is orchestrator-written only.
    if src not in {SOURCE_ORCHESTRATOR, SOURCE_HOST}:
        raise IllegalAttestationSource(
            "attestation source must be orchestrator-written only "
            "(got %r) — sub-agent-authored attestation is rejected and "
            "does not count" % (r.attestation_source,)
        )
    if not is_evidence_source(src):
        raise IllegalAttestationSource(
            "attestation source %r is non-evidence" % (r.attestation_source,)
        )
    r.attestation_source = src

    if r.exit_register_delta is None:
        raise ExecutionLogError("exit-register delta is required (use {} for none)")
    if not isinstance(r.exit_register_delta, dict):
        raise ExecutionLogError("exit-register delta must be a mapping")

    status = str(r.status or "").strip().upper() or GO
    if status not in {GO, NOT_GO, HALT, "GREEN", "RED"}:
        raise ExecutionLogError("status must be GO/NOT_GO/HALT (got %r)" % (r.status,))
    # Normalise GREEN → GO for schema stability.
    if status == "GREEN":
        status = GO
    if status == "RED":
        status = NOT_GO
    r.status = status

    # --- Surface GREEN requires an end-to-end trace ------------------------
    if (
        require_trace_for_surface_green
        and status == GO
        and is_surface_wave(r.wave_id)
    ):
        _require_e2e_trace(
            r,
            root=root,
            trace_artifact=trace_artifact,
        )

    if not r.as_of:
        r.as_of = _utc_now_iso()
    return r


def _require_e2e_trace(
    row: ExecutionLogRow,
    *,
    root: Optional[Path],
    trace_artifact: Optional[Any],
) -> None:
    """Reject surface GREEN when no schema-valid e2e trace is available."""
    base = _root(root)

    # Explicit in-memory / pre-validated artifact wins.
    if trace_artifact is not None:
        if not _trace_mod.is_go_evidence(trace_artifact):
            raise NoEndToEndTrace(
                "%s — surface wave %s reporting GREEN has a trace that is "
                "not GO evidence (dead/invalid/schema-fail)"
                % (NO_E2E_TRACE_MESSAGE, row.wave_id)
            )
        return

    # Path on the row (relative preferred).
    candidates: List[Path] = []
    if row.trace_relpath:
        rel = str(row.trace_relpath).replace("\\", "/").lstrip("/")
        if ".." in Path(rel).parts:
            raise NoEndToEndTrace(
                "%s — trace_relpath may not contain '..'" % NO_E2E_TRACE_MESSAGE
            )
        candidates.append(base / rel)

    # Auto-discover under artifacts/traces/.
    found = _trace_mod.find_trace_for_wave(row.wave_id, root=base)
    if found is not None:
        candidates.append(found)

    for path in candidates:
        if not path.is_file():
            continue
        try:
            art = _trace_mod.load_trace(path, root=base)
        except (_trace_mod.TraceValidationError, _trace_mod.TraceIOError):
            continue
        if _trace_mod.is_go_evidence(art):
            # Record the relative path we accepted.
            try:
                row.trace_relpath = str(path.resolve().relative_to(base.resolve())).replace(
                    "\\", "/"
                )
            except ValueError:
                row.trace_relpath = path.name
            return

    raise NoEndToEndTrace(
        "%s — surface wave %s reporting GREEN has no schema-valid "
        "end-to-end trace artifact; wave is not GO"
        % (NO_E2E_TRACE_MESSAGE, row.wave_id)
    )


# --------------------------------------------------------------------------
# Append
# --------------------------------------------------------------------------


def make_row(
    wave_id: str,
    *,
    commit_sha: str,
    gate_command: str,
    attestation_source: str = SOURCE_ORCHESTRATOR,
    exit_register_delta: Optional[Mapping[str, Any]] = None,
    status: str = GO,
    trace_relpath: str = "",
    note: str = "",
    pass_count: Optional[int] = None,
    fail_count: Optional[int] = None,
    as_of: Optional[str] = None,
) -> ExecutionLogRow:
    """Build an unvalidated row (call :func:`validate_row` / :func:`append`)."""
    return ExecutionLogRow(
        wave_id=str(wave_id).strip(),
        commit_sha=str(commit_sha or "").strip(),
        gate_command=str(gate_command or "").strip(),
        attestation_source=str(attestation_source or "").strip(),
        exit_register_delta=dict(exit_register_delta or {}),
        status=str(status or GO).strip(),
        trace_relpath=str(trace_relpath or "").strip(),
        as_of=as_of if as_of is not None else "",
        note=note or "",
        pass_count=pass_count,
        fail_count=fail_count,
    )


def append(
    row: Union[ExecutionLogRow, Mapping[str, Any]],
    *,
    root: Optional[Path] = None,
    log_relpath: str = EXECUTION_LOG_RELPATH,
    dry_run: bool = False,
    require_trace_for_surface_green: bool = True,
    trace_artifact: Optional[Any] = None,
) -> AppendResult:
    """Validate and append one row to EXECUTION-LOG.md.

    On schema / GO failure raises (so callers can HALT) — never silently
    writes a bad row. Returns :class:`AppendResult` with ``go=True`` only
    when the row is accepted as GO evidence.
    """
    validated = validate_row(
        row,
        root=root,
        require_trace_for_surface_green=require_trace_for_surface_green,
        trace_artifact=trace_artifact,
    )
    go = validated.status == GO
    if dry_run:
        return AppendResult(
            ok=True,
            go=go,
            row=validated,
            message="dry-run — row validated, not written",
        )

    base = _root(root)
    rel = str(log_relpath).replace("\\", "/").lstrip("/")
    if ".." in Path(rel).parts:
        raise ExecutionLogError("log_relpath may not contain '..': %s" % rel)
    out = (base / rel).resolve()
    try:
        out.relative_to(base.resolve())
    except ValueError:
        raise ExecutionLogError(
            "execution-log path escapes containment root: %s" % rel
        ) from None

    block = format_row_markdown(validated)
    out.parent.mkdir(parents=True, exist_ok=True)
    existing = out.read_text(encoding="utf-8") if out.is_file() else ""
    if existing and not existing.endswith("\n"):
        existing += "\n"
    out.write_text(existing + block, encoding="utf-8")
    return AppendResult(
        ok=True,
        go=go,
        row=validated,
        message="appended",
        written_path=rel,
    )


def format_row_markdown(row: ExecutionLogRow) -> str:
    """Render one append block matching the style of existing EXECUTION-LOG rows."""
    delta = row.exit_register_delta or {}
    delta_s = ", ".join("%s=%s" % (k, delta[k]) for k in sorted(delta)) or "(none)"
    lines = [
        "",
        "## Wave %s — append (%s)" % (row.wave_id, row.as_of or _utc_now_iso()),
        "",
        "- **status:** %s" % row.status,
        "- **wave_id:** %s" % row.wave_id,
        "- **commit:** %s" % row.commit_sha,
        "- **gate:** `%s`" % row.gate_command,
        "- **attestation_source:** %s (orchestrator-written only)" % row.attestation_source,
        "- **exit_register_delta:** %s" % delta_s,
    ]
    if row.trace_relpath:
        lines.append("- **trace:** `%s`" % row.trace_relpath)
    if row.pass_count is not None or row.fail_count is not None:
        lines.append(
            "- **tests:** pass %s · fail %s"
            % (
                row.pass_count if row.pass_count is not None else "?",
                row.fail_count if row.fail_count is not None else "?",
            )
        )
    if row.note:
        lines.append("- **note:** %s" % row.note)
    lines.append(
        "- %s — Wave %s %s (schema %s; attestation=%s; commit=%s)"
        % (
            row.as_of or _utc_now_iso(),
            row.wave_id,
            row.status,
            row.schema,
            row.attestation_source,
            row.commit_sha,
        )
    )
    lines.append("")
    return "\n".join(lines)


def is_go(
    row: Union[ExecutionLogRow, Mapping[str, Any], AppendResult],
    *,
    root: Optional[Path] = None,
) -> bool:
    """True when *row* validates as GO evidence (surface trace rules apply)."""
    if isinstance(row, AppendResult):
        return bool(row.ok and row.go)
    try:
        validated = validate_row(row, root=root)
    except ExecutionLogError:
        return False
    return validated.status == GO


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------


def _row_from_mapping(m: Mapping[str, Any]) -> ExecutionLogRow:
    delta = m.get("exit_register_delta", m.get("exit-register-delta", {}))
    if delta is None:
        delta = {}
    if not isinstance(delta, dict):
        # Allow a short string form "none" / "" → empty delta; other strings fail later.
        if isinstance(delta, str) and delta.strip().lower() in {"", "none", "(none)", "{}"}:
            delta = {}
        else:
            delta = {"raw": delta}
    return ExecutionLogRow(
        wave_id=str(m.get("wave_id", m.get("wave-id", "")) or "").strip(),
        commit_sha=str(m.get("commit_sha", m.get("commit", "")) or "").strip(),
        gate_command=str(
            m.get("gate_command", m.get("gate-command", m.get("gate", ""))) or ""
        ).strip(),
        attestation_source=str(
            m.get("attestation_source", m.get("attestation-source", "")) or ""
        ).strip(),
        exit_register_delta=dict(delta),
        status=str(m.get("status", GO) or GO).strip(),
        trace_relpath=str(
            m.get("trace_relpath", m.get("trace", m.get("trace_path", ""))) or ""
        ).strip(),
        as_of=str(m.get("as_of", "") or ""),
        note=str(m.get("note", "") or ""),
        schema=str(m.get("schema", EXECUTION_LOG_SCHEMA) or EXECUTION_LOG_SCHEMA),
        pass_count=m.get("pass_count"),
        fail_count=m.get("fail_count"),
    )


def _utc_now_iso() -> str:
    return (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def _root(root: Optional[Path] = None) -> Path:
    if root is not None:
        return Path(root)
    return Path(__file__).resolve().parents[2]


__all__ = [
    "GO",
    "NOT_GO",
    "HALT",
    "EXECUTION_LOG_RELPATH",
    "EXECUTION_LOG_SCHEMA",
    "NO_E2E_TRACE_MESSAGE",
    "ALLOWED_ATTESTATION_SOURCES",
    "SURFACE_WAVE_MIN",
    "SURFACE_WAVE_MAX",
    "ExecutionLogError",
    "NoEndToEndTrace",
    "IllegalAttestationSource",
    "MissingCommitSha",
    "ExecutionLogRow",
    "AppendResult",
    "parse_wave_number",
    "is_surface_wave",
    "validate_row",
    "make_row",
    "append",
    "format_row_markdown",
    "is_go",
]
