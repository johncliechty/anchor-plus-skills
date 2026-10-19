"""Deterministic standing-preferences PRELOAD + the diffable projection
(steward-chamber W11, C7 — E6).

**The law (E6):** when the talk instruction composes at session start, the
standing preferences — the project's FEEDBACK LEDGER entries plus the GLOBAL
standing rules — are folded into the instruction deterministically, and the
PRELOAD PROJECTION lists EXACTLY the loaded entries. A missing entry is a
DIFFABLE failure (:func:`verify_preload` returns the named missing/extra
ids), never a vibe.

Two sources, both plain JSON, both read-only here:

* **The project feedback ledger** — ``.anchor/chamber/feedback-ledger.json``
  (chamber sidecar; entries recorded from John's standing corrections /
  preferences for THIS project). Missing file → empty-but-valid (zero
  entries loaded, projection empty, still exact).
* **The global standing rules** — ``chamber/standing-rules.json`` in the
  Anchor root (a committed, versioned living artifact; the rules are the
  locked plan's own talk-surface laws, e.g. compose-first / paste-not-submit
  / no fabricated status).

The instruction fold is WIRED into the session-start brief composition
(``commission_session.confirm_and_launch`` — the talk instruction at session
start) via :func:`preload_into_instruction`, which also persists the
projection to the chamber sidecar (``.anchor/chamber/preload.json``) so the
loaded set is durable, inspectable state.

Failure states (surface-bearing wave law): missing ledger → empty-but-valid
(honest zero-entry projection, never a guess); unreadable/garbage ledger →
named ``feedback-ledger-unreadable`` error entry in the projection (the
instruction still composes; the projection SAYS what could not load — a
silent drop is exactly what E6 outlaws).

Stdlib only. No model call, no spawn, no network; the only write is the
chamber-sidecar projection (zero spine writes).
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import chamber_projections as _cp

SCHEMA = "anchor-chamber-preload-v1"

ANCHOR_ROOT = Path(__file__).resolve().parent

#: The committed global standing rules (living artifact, versioned + owned).
STANDING_RULES_PATH = ANCHOR_ROOT / "chamber" / "standing-rules.json"
STANDING_RULES_SCHEMA_VERSION = 1

#: The project-local feedback ledger (chamber sidecar; may be absent).
FEEDBACK_LEDGER_REL = os.path.join(_cp.CHAMBER_SIDECAR_REL,
                                   "feedback-ledger.json")

#: The persisted preload projection (chamber sidecar, derived data).
PRELOAD_PROJECTION_REL = os.path.join(_cp.CHAMBER_SIDECAR_REL,
                                      "preload.json")

#: The fold's header line — the instruction block is delimited so the
#: projection↔instruction diff is mechanical, not fuzzy.
PRELOAD_HEADER = "STANDING PREFERENCES (preloaded — each entry is binding):"

ERROR_LEDGER_UNREADABLE = "feedback-ledger-unreadable"
ERROR_RULES_UNREADABLE = "standing-rules-unreadable"

SOURCE_FEEDBACK = "feedback-ledger"
SOURCE_GLOBAL = "global-rules"


def feedback_ledger_path(folder) -> Path:
    return Path(folder) / FEEDBACK_LEDGER_REL


def projection_path(folder) -> Path:
    return Path(folder) / PRELOAD_PROJECTION_REL


def _entry(entry_id: str, text: str, source: str) -> dict:
    return {"id": str(entry_id), "text": str(text).strip(),
            "source": source}


def load_global_rules(path=None) -> tuple:
    """→ ``(entries, errors)``. Missing file is a NAMED error (the committed
    artifact is expected to exist), unreadable likewise — never a guess."""
    p = Path(path) if path else STANDING_RULES_PATH
    if not p.is_file():
        return [], [{"error": ERROR_RULES_UNREADABLE,
                     "detail": "standing-rules artifact missing"}]
    try:
        doc = json.loads(p.read_text(encoding="utf-8"))
    except (ValueError, OSError) as exc:
        return [], [{"error": ERROR_RULES_UNREADABLE,
                     "detail": str(exc)[:200]}]
    entries = []
    for row in (doc.get("rules") or []):
        if isinstance(row, dict) and row.get("id") and row.get("rule"):
            entries.append(_entry(row["id"], row["rule"], SOURCE_GLOBAL))
    return entries, []


def load_feedback_ledger(folder) -> tuple:
    """→ ``(entries, errors)``. Missing ledger → empty-but-valid (a project
    with no recorded feedback loads zero entries, honestly). Garbage →
    the NAMED unreadable error (the projection carries it; nothing is
    silently dropped)."""
    p = feedback_ledger_path(folder)
    if not p.is_file():
        return [], []
    try:
        doc = json.loads(p.read_text(encoding="utf-8"))
    except (ValueError, OSError) as exc:
        return [], [{"error": ERROR_LEDGER_UNREADABLE,
                     "detail": str(exc)[:200]}]
    entries = []
    rows = doc.get("entries") if isinstance(doc, dict) else None
    for row in (rows or []):
        if isinstance(row, dict) and row.get("id") and row.get("text"):
            entries.append(_entry(row["id"], row["text"], SOURCE_FEEDBACK))
    return entries, []


def load_standing_preferences(folder, *, rules_path=None) -> dict:
    """The deterministic preload set: feedback-ledger entries first (project
    specifics), then the global rules, each entry ``{id, text, source}``.
    Duplicate ids keep the FIRST occurrence (project feedback outranks a
    same-id global rule) — deterministically, never both."""
    fb, fb_err = load_feedback_ledger(folder)
    gl, gl_err = load_global_rules(rules_path)
    seen = set()
    entries = []
    for e in fb + gl:
        if e["id"] in seen:
            continue
        seen.add(e["id"])
        entries.append(e)
    return {"schema": SCHEMA, "entries": entries,
            "errors": fb_err + gl_err}


def instruction_block(entries) -> str:
    """The preload as ONE deterministic instruction block: header + one line
    per entry, ``- [<id>] <text>``. Byte-stable for a given entry list."""
    lines = [PRELOAD_HEADER]
    for e in entries or []:
        lines.append("- [%s] %s" % (e["id"], e["text"]))
    return "\n".join(lines)


def compose_talk_instruction(folder, base_instruction: str = "", *,
                             rules_path=None) -> dict:
    """Compose the session-start talk instruction: the preload block is
    APPENDED to ``base_instruction`` and the projection lists EXACTLY the
    loaded entries. Returns ``{instruction, projection}``."""
    loaded = load_standing_preferences(folder, rules_path=rules_path)
    block = instruction_block(loaded["entries"])
    base = str(base_instruction or "")
    sep = "\n\n" if base and not base.endswith("\n") else "\n"
    instruction = base + sep + block + "\n"
    projection = {
        "schema": SCHEMA,
        "loaded": [dict(e) for e in loaded["entries"]],
        "errors": loaded["errors"],
        "count": len(loaded["entries"]),
    }
    return {"instruction": instruction, "projection": projection}


def preload_into_instruction(folder, base_instruction: str = "", *,
                             rules_path=None, persist: bool = True) -> dict:
    """The session-start wiring point (``commission_session.
    confirm_and_launch``): compose + PERSIST the projection to the chamber
    sidecar so the loaded set survives as inspectable state."""
    out = compose_talk_instruction(folder, base_instruction,
                                   rules_path=rules_path)
    if persist:
        _cp.atomic_write_json(projection_path(folder), out["projection"])
    return out


def load_projection(folder) -> dict | None:
    p = projection_path(folder)
    if not p.is_file():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return None


def verify_preload(instruction: str, projection: dict) -> dict:
    """THE E6 DIFF: every projected entry must be PRESENT in the instruction
    (its ``- [<id>] <text>`` line), and every preload line in the
    instruction must be projected. Returns the named diff — empty lists ==
    exact. A missing entry is a diffable failure, not a vibe."""
    text = str(instruction or "")
    projected = (projection or {}).get("loaded") or []
    missing = [e["id"] for e in projected
               if ("- [%s] %s" % (e["id"], e["text"])) not in text]
    # The other direction: preload lines present in the instruction but not
    # projected (a smuggled entry is as much a lie as a dropped one).
    proj_lines = {"- [%s] %s" % (e["id"], e["text"]) for e in projected}
    in_block = []
    seen_header = False
    for ln in text.splitlines():
        if ln.strip() == PRELOAD_HEADER:
            seen_header = True
            continue
        if seen_header:
            if ln.startswith("- ["):
                in_block.append(ln.rstrip())
            elif ln.strip() == "":
                continue
            else:
                seen_header = False
    extra = [ln for ln in in_block if ln not in proj_lines]
    return {"exact": not missing and not extra,
            "missing_from_instruction": missing,
            "unprojected_in_instruction": extra}
