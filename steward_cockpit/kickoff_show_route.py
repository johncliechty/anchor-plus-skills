"""Gate 5 / Wave 8 - Phase 4.2: the cockpit's ONLY kickoff HTTP exposure.

``GET /api/ecgberht/kickoff_show?pid=<project>&effort=<rel>`` resolves here:
anchor_gui's ``handle_ecgberht_kickoff_show`` maps the pid to a project folder
and hands this module the folder plus the effort rel-name. The effort resolves
through the steward cockpit's EXISTING ``_effort_dir`` guard - an effort the
discovery does not know is refused 404 before anything is read - and the
answer is the Wave 7 pass-through reader's read-model row, untouched.

READ-MODEL ONLY. This module invokes no mutation path: no write, no
subprocess, no bridge spawn, no store access (the reader itself never opens
the append-only store). Confirm and replay stay conversational / bridge-CLI
verbs with zero network exposure - the cockpit exposes kickoff VIEWING only
(the Gate 5 North Star). A guard test walks this module's AST to keep it so.

Failure states are machine-readable rows with named status codes AND
user-visible text; ``unknown`` (source not readable) and ``empty-but-valid``
are SEPARATE rows, and the unknown-EFFORT refusal is its own row distinct
from both. Stdlib only; ASCII on purpose.
"""

from __future__ import annotations

from steward_cockpit import kickoff_reader
from steward_cockpit.steward_routes import _effort_dir

SURFACE = "kickoff_show"

# The guard refusal's own row: the effort rel-name is not one discovery knows.
# Distinct from the reader's source-UNKNOWN row (a known effort whose
# projection file is absent/unreadable).
CODE_UNKNOWN_EFFORT = "ANCHOR_KICKOFF_UNKNOWN_EFFORT"
TEXT_UNKNOWN_EFFORT = (
    "unknown effort - the requested effort is not one this project's"
    " discovery knows, so nothing was read."
)

# HTTP status per read-model state. OPEN and EMPTY are valid 200 answers
# (an honest 'draft, not applied' / 'nothing yet'); a source the reader cannot
# read is 404; a projection outside the contract is refused 502, never guessed.
KICKOFF_SHOW_HTTP_STATUS = {
    CODE_UNKNOWN_EFFORT: 404,
    kickoff_reader.CODE_CONFIRMED: 200,
    kickoff_reader.CODE_OPEN: 200,
    kickoff_reader.CODE_UNKNOWN: 404,
    kickoff_reader.CODE_EMPTY: 200,
    kickoff_reader.CODE_MALFORMED: 502,
}

# Machine-readable read-only guards for this surface - what the endpoint is
# FORBIDDEN to do. The AST guard test enforces them against this source.
ROUTE_GUARDS = {
    "read_only": True,
    "pass_through": True,
    "mutates": False,
    "executes": False,
    "spawns_bridge": False,
}


def kickoff_show(proot, effort_rel):
    """The endpoint's whole substance: ``(json_payload, http_status)``.

    Resolves ``effort_rel`` through the existing ``_effort_dir`` guard
    (unknown refused, nothing read), then passes the Wave 7 reader's
    read-model row through verbatim. Invokes no mutation path.
    """
    rel = str(effort_rel or "").strip()
    edir = _effort_dir(proot, rel)
    if edir is None:
        return (
            {
                "ok": False,
                "error": "unknown effort",
                "code": CODE_UNKNOWN_EFFORT,
                "status_code": CODE_UNKNOWN_EFFORT,
                "text": TEXT_UNKNOWN_EFFORT,
                "user_text": TEXT_UNKNOWN_EFFORT,
                "surface": SURFACE,
                "effort": rel,
                "read_only": True,
            },
            KICKOFF_SHOW_HTTP_STATUS[CODE_UNKNOWN_EFFORT],
        )
    row = dict(kickoff_reader.read_kickoff_projection(edir))
    row["surface"] = SURFACE
    row["effort"] = rel
    return row, KICKOFF_SHOW_HTTP_STATUS.get(row.get("code"), 502)


def kickoff_show_failure_table():
    """The failure-state table for this surface: the guard refusal row plus
    the reader's five rows, each with the HTTP status this endpoint answers.
    ``unknown-effort``, ``unknown``, and ``empty-but-valid`` stay SEPARATE.
    """
    rows = [
        {
            "state": "unknown-effort",
            "surface": SURFACE,
            "status_code": CODE_UNKNOWN_EFFORT,
            "http_status": KICKOFF_SHOW_HTTP_STATUS[CODE_UNKNOWN_EFFORT],
            "user_text": TEXT_UNKNOWN_EFFORT,
        }
    ]
    for reader_row in kickoff_reader.kickoff_reader_failure_table():
        row = dict(reader_row)
        row["surface"] = SURFACE
        row["http_status"] = KICKOFF_SHOW_HTTP_STATUS[row["status_code"]]
        rows.append(row)
    return tuple(rows)
