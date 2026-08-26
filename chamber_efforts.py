"""Multiple seals per project — effort threads over ONE campaign.

(2026-08-15, John, third ask) "When I get done with the effort I'm going to
want to open another one and work on something different within this project…
a top window with tiles — click one, it opens with all the dialog; minimize
it; start a new one."

WHAT AN EFFORT IS HERE, honestly: a named CONVERSATION THREAD with the
steward, over the one shared campaign. The engine keeps exactly one roadmap,
one strip, one gate queue per project folder — so the flow rail and the run
queue stay shared, and the page warns when a second seal commissions while a
run is live (the engine would refuse the collision anyway; the warning just
says it BEFORE money moves). Splitting the roadmap per effort is deliberately
NOT attempted Anchor-side: two writers on one narrative spine is the exact
defect class the chamber build spent a week paying for.

THE DEFAULT EFFORT ("campaign") is the thread that already exists — the
engine's own conversation log. Additional efforts get their own Anchor-side
thread files; every turn still lands in the engine's global log too (it is
the audit trail), these files only decide what each seal PAINTS.

Storage: ``.anchor/chamber/efforts.json`` + ``effort-<id>-dialogue.json``.
Atomic writes, bounded reads, stdlib only.
"""
from __future__ import annotations

import json
import os
import re
import time
import uuid
from pathlib import Path

# The server's shared write lock — two tabs (or the laptop and the desktop
# over Tailscale) hitting one service must not lose each other's writes in a
# read-modify-write race. In-process is sufficient: one NSSM service owns the
# port exclusively (SO_EXCLUSIVEADDRUSE).
try:
    from paths import WRITE_LOCK as _LOCK
except Exception:  # standalone import (tests, tooling)
    import threading
    _LOCK = threading.Lock()

CHAMBER_DIR = ".anchor/chamber"
EFFORTS_REL = CHAMBER_DIR + "/efforts.json"
SCHEMA = "chamber-efforts-v1"

#: The always-present default effort: the campaign thread the engine owns.
CAMPAIGN_ID = "campaign"

#: A thread is long-lived, not unbounded.
DIALOGUE_MAX_TURNS = 500
DIALOGUE_PAINT_LIMIT = 40

_ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,40}$")


def _efforts_path(folder) -> Path:
    return Path(folder) / EFFORTS_REL


def _dialogue_path(folder, effort_id: str) -> Path:
    return Path(folder) / CHAMBER_DIR / ("effort-%s-dialogue.json" % effort_id)


def _atomic_write(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=1),
                   encoding="utf-8")
    os.replace(tmp, path)


def valid_effort_id(effort_id) -> bool:
    return bool(_ID_RE.match(str(effort_id or "")))


def load_efforts(folder) -> dict:
    """``{schema, active, efforts:[{id,name,status,created_at,note}]}``.
    Missing/corrupt → the honest default: just the campaign thread."""
    p = _efforts_path(folder)
    default = {"schema": SCHEMA, "active": CAMPAIGN_ID,
               "efforts": [{"id": CAMPAIGN_ID, "name": "the campaign",
                            "status": "active", "created_at": None,
                            "note": "the project's own thread"}]}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default
    if not isinstance(data, dict) or not isinstance(data.get("efforts"), list):
        return default
    if not any(e.get("id") == CAMPAIGN_ID for e in data["efforts"]
               if isinstance(e, dict)):
        data["efforts"].insert(0, default["efforts"][0])
    if not valid_effort_id(data.get("active")):
        data["active"] = CAMPAIGN_ID
    return data


#: Tiles must stay legible; a runaway strip helps nobody.
MAX_OPEN_EFFORTS = 24


def create_effort(folder, name: str) -> dict:
    """A new seal. Returns the updated store; the new effort becomes active.
    Refuses past the cap — with the reason, never silently."""
    name = (name or "").strip()[:80] or "a new effort"
    with _LOCK:
        store = load_efforts(folder)
        open_count = sum(1 for e in store["efforts"]
                         if e.get("status") != "done")
        if open_count >= MAX_OPEN_EFFORTS:
            store["capped"] = ("%d open efforts — finish or park some before "
                               "starting another" % open_count)
            return store
        eid = "e-" + uuid.uuid4().hex[:8]
        store["efforts"].append({"id": eid, "name": name, "status": "active",
                                 "created_at": time.time(), "note": ""})
        store["active"] = eid
        _atomic_write(_efforts_path(folder), store)
    return store


def set_effort(folder, effort_id: str, *, status: str | None = None,
               active: bool = False, name: str | None = None) -> dict:
    """Park / finish / reopen / rename / focus one effort. Unknown id → the
    store unchanged (an honest no-op, never an invention)."""
    if not valid_effort_id(effort_id):
        return load_efforts(folder)
    with _LOCK:
        store = load_efforts(folder)
        for e in store["efforts"]:
            if e.get("id") != effort_id:
                continue
            if status in ("active", "parked", "done") and effort_id != CAMPAIGN_ID:
                e["status"] = status
            if name is not None and effort_id != CAMPAIGN_ID:
                e["name"] = str(name).strip()[:80] or e.get("name")
            if active:
                store["active"] = effort_id
            _atomic_write(_efforts_path(folder), store)
            break
    return store


def read_dialogue(folder, effort_id: str,
                  limit: int = DIALOGUE_PAINT_LIMIT) -> list:
    """The thread's tail, oldest-first, ``[{role,text}]``. The campaign id has
    no file here — its thread IS the engine's log (chamber_open reads it)."""
    if not valid_effort_id(effort_id) or effort_id == CAMPAIGN_ID:
        return []
    try:
        data = json.loads(_dialogue_path(folder, effort_id)
                          .read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    turns = data.get("turns") if isinstance(data, dict) else None
    if not isinstance(turns, list):
        return []
    out = []
    for t in turns[-max(0, int(limit)):]:
        if not isinstance(t, dict):
            continue
        text = str(t.get("text") or "").strip()
        if text:
            out.append({"role": "john" if t.get("role") == "john"
                        else "steward", "text": text})
    return out


def append_dialogue(folder, effort_id: str, turns: list) -> bool:
    """Append turns to an effort thread. Bounded; atomic; never raises."""
    if not valid_effort_id(effort_id) or effort_id == CAMPAIGN_ID:
        return False
    clean = [{"role": "john" if t.get("role") == "john" else "steward",
              "text": str(t.get("text") or "").strip(), "at": time.time()}
             for t in (turns or [])
             if isinstance(t, dict) and str(t.get("text") or "").strip()]
    if not clean:
        return False
    p = _dialogue_path(folder, effort_id)
    with _LOCK:
        return _append_locked(p, clean)


def _append_locked(p: Path, clean: list) -> bool:
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        if not isinstance(data, dict) or not isinstance(data.get("turns"), list):
            data = {"schema": SCHEMA, "turns": []}
    except (OSError, ValueError):
        data = {"schema": SCHEMA, "turns": []}
    data["turns"] = (data["turns"] + clean)[-DIALOGUE_MAX_TURNS:]
    try:
        _atomic_write(p, data)
        return True
    except OSError:
        return False
