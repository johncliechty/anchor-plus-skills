"""run_pulse DATA CORE (steward-chamber W7 — wire-homing row ``run_pulse``).

C12's law for this wave: run_pulse is WIRED into the M1 rail, never
reimplemented. This module is the SPLIT the plan orders — the data-producing
core extracted from ``anchor_gui.handle_ecgberht_run_pulse`` (the owner
symbol, which REMAINS in anchor_gui.py and now delegates here), serving TWO
consumers:

* **the existing tiles** — ``handle_ecgberht_run_pulse`` keeps its exact
  HTTP contract (the tiles keep consuming until the C11 signed-parity
  retirement) by calling :func:`pulse_payload` and sending the result;
* **the chamber step slot** — the M1 rail's running-step ⏱ card
  (:func:`step_slot` over a payload for the live poll;
  :func:`step_slot_from_record` over the banked run record for the
  zero-PTY open paint).

CHARACTERIZED, BUG-FOR-BUG (the no-silent-reimplementation law): parity is
proven against the COMMITTED pulse-stream replay fixtures
(``tests/fixtures/chamber/pulse-replay``) BEFORE anything is deleted, and
the split preserves the owned code's observed behavior exactly — including
one long-standing quirk, kept deliberately:

    the live-read branch looks up ``"chunk"`` / ``"cursor"`` keys on the
    ``terminal_session.read_since`` result, whose actual keys are
    ``"text"`` / ``"next"``. The live chunk therefore always reads empty
    and the cursor echoes the caller's — so the served tail and the ⏱
    status scan come from the run record's BANKED ``transcript_tail``
    (the catch-and-store law: "you have to catch the status and store
    it"). Changing that is a BEHAVIOR change: per the wire-homing kill
    branch it would need a scoped wire-amendment to John, never a silent
    fix inside a split.

Stdlib only. Read-only: no spawn, no network, no PTY writes (the injected
``read_since_fn`` is the session substrate's own cursor read).
"""
from __future__ import annotations

import re
from pathlib import Path

#: The tail cap the tiles have always served (characterized).
TAIL_CAP = 4000

#: How far past the last ⏱ / [HH:MM] marker the status block extends
#: (characterized from the owner).
STATUS_BLOCK_SPAN = 700

#: Named step-slot states for the chamber consumer (the M1 runcard faces).
SLOT_STATUS = "status"            # a captured ⏱ block rides the card
SLOT_PRE_EMISSION = "pre-emission"  # drawn AG-PRE-EMISSION-OPEN face

_ANSI_RE = None
_STATUS_MARK_RE = None


def strip_terminal_noise(s) -> str:
    """Strip ANSI/OSC control sequences + CRs so a PTY tail reads as text.
    Stdlib re only; never raises. (Moved verbatim from anchor_gui — the
    owner now delegates here; tests/test_steward_pulse.py pins behavior.)"""
    global _ANSI_RE
    try:
        if _ANSI_RE is None:
            _ANSI_RE = re.compile(
                r"\x1b\[[0-9;?]*[ -/]*[@-~]|\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)"
                r"|\x1b[@-_]|[\x00-\x08\x0b\x0c\x0e-\x1a\x1c-\x1f]")
        return _ANSI_RE.sub("", str(s)).replace("\r", "")
    except Exception:
        return str(s)


def read_face_north_star(folder):
    """The '## North star' blockquote from the project's ECGBERHT.md face —
    a display line for the pulse tile. Read-only, best-effort, never raises.
    (Moved verbatim from anchor_gui.)"""
    try:
        text = (Path(folder) / "ECGBERHT.md").read_text(
            encoding="utf-8", errors="replace")
        lines, grab = [], False
        for ln in text.splitlines():
            if ln.strip().lower().startswith("## north star"):
                grab = True
                continue
            if grab:
                if ln.startswith("#") or (lines and not ln.strip()):
                    break
                if ln.lstrip().startswith(">"):
                    lines.append(ln.lstrip()[1:].strip())
        star = " ".join(x for x in lines if x).replace("**", "")
        return star or None
    except Exception:
        return None


def latest_status_block(text):
    """The skills' own ⏱/[HH:MM] 10-minute status table, when one rode the
    output — John's #1 want on the pulse. Last occurrence wins. (Moved
    verbatim from the owner's ``_latest_status_block``.)"""
    global _STATUS_MARK_RE
    try:
        if _STATUS_MARK_RE is None:
            _STATUS_MARK_RE = re.compile(r"⏱|^\[\d{2}:\d{2}\]", re.M)
        hits = [m.start() for m in _STATUS_MARK_RE.finditer(text)]
        if not hits:
            return None
        return text[hits[-1]:hits[-1] + STATUS_BLOCK_SPAN].strip() or None
    except Exception:
        return None


def _default_load_record(folder, session_id):
    import commission_session as _cs
    return _cs.load_run_record(folder, session_id)


def _default_read_since(session_id, cursor):
    import terminal_session as _ts
    return _ts.read_since(session_id, cursor)


def pulse_payload(folder, session_id, cursor=0, *,
                  load_record_fn=None, read_since_fn=None,
                  north_star_fn=None):
    """The run_pulse payload — EXACTLY what the tile endpoint has always
    served (the characterized core). Returns ``None`` when the run record is
    absent (the HTTP owner maps that to its 404 ``unknown_run``).

    ``read_since_fn`` / ``load_record_fn`` are the replay seams the committed
    pulse-stream fixtures drive; production callers take the defaults (the
    real ``terminal_session.read_since`` / ``commission_session
    .load_run_record``).
    """
    load_record_fn = load_record_fn or _default_load_record
    read_since_fn = read_since_fn or _default_read_since
    north_star_fn = north_star_fn or read_face_north_star

    rec = load_record_fn(folder, session_id)
    if not rec:
        return None
    out = {
        "ok": True,
        "session_id": session_id,
        "skill": rec.get("skill"),
        "step_id": rec.get("step_id"),
        "outcome": rec.get("outcome"),
        "at": rec.get("at"),
        "directive": rec.get("directive"),
        "auto_chain": rec.get("auto_chain"),
        "north_star": north_star_fn(folder),
    }

    # Live tail while running; the banked tail once it stopped. The ⏱ status
    # scan reads the WHOLE retained buffer — a status table emitted between
    # polls must be CAUGHT, not missed because the fresh chunk lacked one.
    # (Characterized: the "chunk"/"cursor" lookups are the owner's own — see
    # the module docstring's quirk note. Do NOT "fix" them here.)
    full_text = ""
    try:
        r = read_since_fn(session_id, cursor)
        chunk = (r or {}).get("chunk") or ""
        try:
            full = read_since_fn(session_id, 0)
            full_text = strip_terminal_noise((full or {}).get("chunk") or "")
        except Exception:
            full_text = ""
        if not chunk and cursor == 0 and rec.get("transcript_tail"):
            # A parked/dead session reads EMPTY, not an exception — the
            # banked tail is the truth.
            out["tail"] = strip_terminal_noise(
                rec["transcript_tail"])[-TAIL_CAP:]
            out["live"] = False
        else:
            out["tail"] = strip_terminal_noise(chunk)[-TAIL_CAP:]
            out["live"] = True
        out["cursor"] = (r or {}).get("cursor", cursor)
    except Exception:
        out["tail"] = strip_terminal_noise(
            rec.get("transcript_tail") or "")[-TAIL_CAP:]
        out["cursor"] = cursor
        out["live"] = False
    out["latest_status"] = latest_status_block(full_text) \
        or latest_status_block(out.get("tail") or "") \
        or latest_status_block(
            strip_terminal_noise(rec.get("transcript_tail") or ""))
    return out


# ── The chamber consumers (M1 running-step ⏱ slot) ──────────────────────────

def step_slot(payload) -> dict | None:
    """The M1 running-step ⏱ slot, derived from a pulse payload (the live
    poll's consumer). ``None`` for a ``None`` payload (unknown run).

    ``state`` is ``"status"`` when a captured ⏱/[HH:MM] block exists, else
    the drawn ``"pre-emission"`` face (AG-PRE-EMISSION-OPEN) — never a
    fabricated table.
    """
    if not payload:
        return None
    block = payload.get("latest_status")
    return {
        "session_id": payload.get("session_id"),
        "skill": payload.get("skill"),
        "step_id": payload.get("step_id"),
        "started_at": payload.get("at"),
        "live": payload.get("live"),
        "state": SLOT_STATUS if block else SLOT_PRE_EMISSION,
        "status_block": block,
    }


def step_slot_from_record(rec) -> dict | None:
    """The SAME ⏱ slot derived from the banked run record alone — the open
    paint's consumer (zero PTY touches on the open path; the record's
    ``transcript_tail`` is exactly the buffer the pulse core scans on its
    dominant path, so open-seed and live-poll agree by construction)."""
    if not isinstance(rec, dict):
        return None
    block = latest_status_block(
        strip_terminal_noise(rec.get("transcript_tail") or ""))
    return {
        "session_id": rec.get("session_id"),
        "skill": rec.get("skill"),
        "step_id": rec.get("step_id"),
        "started_at": rec.get("at"),
        "live": rec.get("outcome") == "running",
        "state": SLOT_STATUS if block else SLOT_PRE_EMISSION,
        "status_block": block,
    }
