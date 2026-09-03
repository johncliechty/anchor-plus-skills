"""Gate 5 / Wave 7 - Phase 4.1: the Anchor pass-through reader for Ecgberht's
kickoff projection contract.

PASS-THROUGH ONLY. This module loads ``<folder>/.ecgberht/kickoff/projection.json``
- the read-model Ecgberht's confirmed-lineage projection writer persists - and
renders it verbatim. It NEVER derives a second truth: it does not open the
append-only store, does not recompute a hash, does not re-sort a lineage, and
holds no session state, so a restart paints exactly what is on disk. It is
read-only by construction: no write, no mutation, no subprocess, no execution
path exists in this file (a guard test walks this module's AST to keep it so).

``render_kickoff_passthrough`` here and ``renderKickoffPassthrough`` in
Ecgberht's ``scripts/kickoff-golden-fixture.mjs`` are the SAME template in two
languages - that duplication IS the cross-language contract: the golden test
asserts byte-equality between what Node writes and what this reader renders.
``canonical_kickoff_bytes`` mirrors Ecgberht's sorted-key UTF-8/no-float
serialization for the same reason. Change either side in both places or the
golden test fails.

Failure states are machine-readable rows with ``unknown`` and ``empty`` as
SEPARATE answers: a missing or unreadable source file is UNKNOWN (this reader
refuses to guess and never consults the store), an empty file is EMPTY, an open
draft is OPEN (draft, not applied), a confirmed projection is CONFIRMED, and
anything that does not parse as the contract is MALFORMED. Source is ASCII on
purpose. Stdlib only.
"""

from __future__ import annotations

import json
from pathlib import Path

KICKOFF_PROJECTION_SCHEMA = "ecgberht-kickoff-projection-v0"
KICKOFF_PROJECTION_FILE = "projection.json"
KICKOFF_DIR_REL = ".ecgberht/kickoff"
KICKOFF_PROJECTION_REL = KICKOFF_DIR_REL + "/" + KICKOFF_PROJECTION_FILE

# The named read bound (mirrors the store's own 16 MiB bound). A larger file is
# refused unread - its state is honestly UNKNOWN, never a partial guess.
KICKOFF_PROJECTION_MAX_BYTES = 16 * 1024 * 1024

# Machine-readable read-only guards - what this reader is FORBIDDEN to do.
# The AST guard test enforces these claims against this module's source.
READER_GUARDS = {
    "read_only": True,
    "pass_through": True,
    "derives_from_store": False,
    "mutates": False,
    "executes": False,
}

# Status codes. CONFIRMED and OPEN mirror Ecgberht's own lifecycle codes so one
# vocabulary spans both repos; the source-file rows are this reader's own.
CODE_CONFIRMED = "KICKOFF_CONFIRMED"
CODE_OPEN = "KICKOFF_OPEN_UNCONFIRMED"
CODE_UNKNOWN = "ANCHOR_KICKOFF_SOURCE_UNKNOWN"
CODE_EMPTY = "ANCHOR_KICKOFF_SOURCE_EMPTY"
CODE_MALFORMED = "ANCHOR_KICKOFF_MALFORMED"

READER_TEXT = {
    CODE_CONFIRMED:
        "Kickoff confirmed - rendered pass-through from Ecgberht's projection.",
    CODE_OPEN:
        "An open kickoff draft exists but nothing is confirmed - draft, not"
        " applied; nothing authoritative to render.",
    CODE_UNKNOWN:
        "Kickoff state unknown - the projection file is not readable here"
        " (<error>). This reader never derives state from the store, so it"
        " reports unknown rather than guessing.",
    CODE_EMPTY:
        "The kickoff projection file is empty - nothing confirmed to render.",
    CODE_MALFORMED:
        "The kickoff projection does not parse as the projection contract"
        " (<error>) - refused rather than guessed; Ecgberht's receipt lineage"
        " stays authoritative.",
}

# The confirmed block fields the pass-through rendering quotes verbatim; a
# document missing one is malformed input, not something to improvise around.
_REQUIRED_CONFIRMED_KEYS = (
    "version",
    "proposal_hash",
    "receipt_hash",
    "rendered_prose",
    "who",
    "confirmed_at",
)
_REQUIRED_DRAFT_KEYS = ("version", "proposal_hash", "goal", "applied")


def kickoff_reader_failure(code, error=None, **extra):
    """One failure row: named status code AND user-visible text, never a guess."""
    err = error if error is not None else str(code).lower()
    text = READER_TEXT[code].replace("<error>", str(err))
    row = {
        "ok": False,
        "code": code,
        "status_code": code,
        "error": err,
        "text": text,
        "user_text": text,
        "authoritative": False,
        "read_only": True,
        "pass_through": True,
        "derives_from_store": False,
    }
    row.update(extra)
    return row


def kickoff_reader_failure_table():
    """The machine-readable failure-state table for this surface.

    ``unknown`` and ``empty`` source files are SEPARATE rows, never collapsed;
    OPEN, CONFIRMED, and malformed input each answer with their own row.
    """
    def row(state, code):
        return {
            "state": state,
            "surface": "anchor_kickoff_reader",
            "status_code": code,
            "user_text": READER_TEXT[code],
        }

    return (
        row("confirmed", CODE_CONFIRMED),
        row("open", CODE_OPEN),
        row("unknown", CODE_UNKNOWN),
        row("empty-but-valid", CODE_EMPTY),
        row("malformed", CODE_MALFORMED),
    )


def render_kickoff_passthrough(projection):
    """The pass-through rendering: every byte comes verbatim from projection
    fields or from this fixed template - nothing recomputed, nothing consulted.

    Mirrored byte-for-byte by renderKickoffPassthrough in Ecgberht's
    scripts/kickoff-golden-fixture.mjs; change BOTH or the golden test fails.
    """
    confirmed = projection["confirmed"]
    lines = [
        "# Kickoff - confirmed v" + str(confirmed["version"]),
        "",
        str(confirmed["rendered_prose"]).rstrip("\n"),
        "",
        "Confirmed by " + str(confirmed["who"]) + " at "
        + str(confirmed["confirmed_at"]) + ".",
        "Record sha256 " + str(confirmed["proposal_hash"]) + ".",
        "Receipt sha256 " + str(confirmed["receipt_hash"]) + ".",
    ]
    draft = projection.get("open_draft")
    if draft:
        lines += [
            "",
            "Draft v" + str(draft["version"]) + " (" + str(draft["proposal_hash"])
            + ") - draft, not applied: " + str(draft["goal"]),
            "This draft is not authoritative; the confirmed kickoff above stays"
            " in force.",
        ]
    lines.append("")
    return "\n".join(lines)


_MAX_SAFE_INTEGER = 2 ** 53 - 1


def _emit_canonical(value, out, at):
    if value is None:
        out.append("null")
        return
    if value is True:
        out.append("true")
        return
    if value is False:
        out.append("false")
        return
    if isinstance(value, str):
        out.append(json.dumps(value, ensure_ascii=False))
        return
    if isinstance(value, int):
        if abs(value) > _MAX_SAFE_INTEGER:
            raise ValueError("non_integer_number at " + at)
        out.append(str(value))
        return
    if isinstance(value, float):
        raise ValueError("non_integer_number at " + at)
    if isinstance(value, list):
        out.append("[")
        for i, item in enumerate(value):
            if i > 0:
                out.append(",")
            _emit_canonical(item, out, at + "[" + str(i) + "]")
        out.append("]")
        return
    if isinstance(value, dict):
        # Keys sort by UTF-16 code unit, exactly as Ecgberht's emitter sorts.
        keys = sorted(value.keys(), key=lambda k: k.encode("utf-16-be"))
        out.append("{")
        for i, key in enumerate(keys):
            if i > 0:
                out.append(",")
            out.append(json.dumps(key, ensure_ascii=False))
            out.append(":")
            _emit_canonical(value[key], out, at + "." + key)
        out.append("}")
        return
    raise ValueError("non_canonical_value at " + at)


def canonical_kickoff_bytes(value):
    """Sorted-key, UTF-8, no-float JSON bytes - the mirror of Ecgberht's
    canonicalKickoffBytes. Re-serializing a parsed projection.json through this
    function must reproduce the file's bytes exactly (plus the trailing
    newline the writer appends); raises ValueError on a value outside the
    canonical contract.
    """
    out = []
    _emit_canonical(value, out, "$")
    return "".join(out).encode("utf-8")


def kickoff_projection_path(project_path):
    """Absolute path of projection.json under an Ecgberht project folder."""
    return Path(project_path).resolve() / KICKOFF_PROJECTION_REL


def read_kickoff_projection_file(projection_path, max_bytes=KICKOFF_PROJECTION_MAX_BYTES):
    """Load ONE projection.json as the pass-through read-model it is.

    Never derives, never writes, never consults the store. Missing or
    unreadable answers UNKNOWN; an empty file answers EMPTY; an open draft
    document answers OPEN (draft, not applied); anything outside the contract
    answers MALFORMED; a well-formed confirmed projection answers ok with the
    document and its rendering passed through verbatim.
    """
    p = Path(projection_path)
    try:
        size = p.stat().st_size
    except FileNotFoundError as exc:
        return kickoff_reader_failure(
            CODE_UNKNOWN, error="projection_file_absent", detail=str(exc),
        )
    except OSError as exc:
        return kickoff_reader_failure(
            CODE_UNKNOWN, error="projection_file_unreadable", detail=str(exc),
        )
    if size > max_bytes:
        return kickoff_reader_failure(
            CODE_UNKNOWN,
            error="projection_file_exceeds_bound",
            size=size,
            max_bytes=max_bytes,
        )
    try:
        raw = p.read_bytes()
    except OSError as exc:
        return kickoff_reader_failure(
            CODE_UNKNOWN, error="projection_file_unreadable", detail=str(exc),
        )
    if raw.strip() == b"":
        return kickoff_reader_failure(CODE_EMPTY, error="projection_file_empty")
    try:
        doc = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        return kickoff_reader_failure(
            CODE_MALFORMED, error="projection_json_unparseable",
        )
    if not isinstance(doc, dict) or doc.get("schema") != KICKOFF_PROJECTION_SCHEMA:
        return kickoff_reader_failure(
            CODE_MALFORMED, error="projection_schema_unknown",
        )
    state = doc.get("state")
    if state == "open":
        return kickoff_reader_failure(
            CODE_OPEN,
            error="open_draft_not_applied",
            state="open",
            open_draft=doc.get("open_draft"),
        )
    if state != "confirmed":
        return kickoff_reader_failure(
            CODE_MALFORMED, error="projection_state_unknown",
        )
    confirmed = doc.get("confirmed")
    if (
        not isinstance(confirmed, dict)
        or not isinstance(doc.get("intent"), dict)
        or not isinstance(doc.get("execution"), dict)
        or any(key not in confirmed for key in _REQUIRED_CONFIRMED_KEYS)
    ):
        return kickoff_reader_failure(
            CODE_MALFORMED, error="projection_shape_invalid",
        )
    draft = doc.get("open_draft")
    if draft is not None and (
        not isinstance(draft, dict)
        or any(key not in draft for key in _REQUIRED_DRAFT_KEYS)
    ):
        return kickoff_reader_failure(
            CODE_MALFORMED, error="open_draft_shape_invalid",
        )
    return {
        "ok": True,
        "state": "confirmed",
        "code": CODE_CONFIRMED,
        "status_code": CODE_CONFIRMED,
        "user_text": READER_TEXT[CODE_CONFIRMED],
        "authoritative": True,
        "read_only": True,
        "pass_through": True,
        "derives_from_store": False,
        "projection": doc,
        "projection_path": str(p),
        "version": confirmed["version"],
        "proposal_hash": confirmed["proposal_hash"],
        "receipt_hash": confirmed["receipt_hash"],
        "open_draft": draft,
        "rendered": render_kickoff_passthrough(doc),
    }


def read_kickoff_projection(project_path, max_bytes=KICKOFF_PROJECTION_MAX_BYTES):
    """Read the projection under an Ecgberht project folder, pass-through."""
    return read_kickoff_projection_file(
        kickoff_projection_path(project_path), max_bytes=max_bytes,
    )
