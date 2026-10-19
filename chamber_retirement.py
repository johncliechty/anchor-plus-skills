"""C11 tile retirement on SIGNED rail+STATUS parity (steward-chamber W12).

The law, from the plan and the W9 inventory's own ``signing_law``: the
bottom run tiles are removed ONLY after the tile-affordance functional
inventory + parity map resolves EVERY row to a live rail/STATUS equivalent
or a John-signed accepted loss, AND rail+STATUS parity is SIGNED. No tile
code is deleted before the signature. The inventory landed in W9 UNSIGNED
(``signed_by_john: false``); W12 records the signature when John rules.

This module is that gate — the ONE callable retirement must cross:

* :func:`parity_state` — every inventory row classified: a VERIFIED live
  equivalent (W9's marker checks re-run at the seam), or a PENDING John
  ruling (proposed-equivalent / proposed-loss with decision material), or a
  John-ruled row (an additive ``parity.john_ruling`` field recorded at
  signing: ``accepted-loss`` or ``equivalent-signed`` — additive so the W9
  checker's kind vocabulary is never rewritten).
* :func:`signature_state` — signed iff BOTH the inventory's
  ``signed_by_john`` flag AND the committed gate record
  (``chamber/TILE-RETIREMENT-GATE.md``) carry the signature; disagreement
  fails CLOSED (a half-signed gate is unsigned).
* :func:`retirement_allowed` — the named refusal until parity is green,
  every row is resolved-or-ruled, and the signature exists. Never a write,
  never a deletion — the gate ANSWERS; it does not act.

Honesty note (W12 audit): W9's ``tile_affordance_problems`` CI gate had no
test naming it when this wave opened (the file its law cites,
``tests/test_chamber_close_ci_w9.py``, is not in the tree). The W12
retirement suite exercises it at the seam and
``chamber/W12-AUDIT-REPORT.md`` records the reconciliation.

Stdlib only. Read-only.
"""
from __future__ import annotations

import re
from pathlib import Path

import chamber_status_overlay as cso

ANCHOR_ROOT = Path(__file__).resolve().parent
GATE_RECORD_PATH = ANCHOR_ROOT / "chamber" / "TILE-RETIREMENT-GATE.md"

#: Named findings — a refusal is always attributable (C11).
FINDING_UNSIGNED = "W12-TILE-RETIREMENT-UNSIGNED"
FINDING_PARITY_PROBLEMS = "W12-TILE-PARITY-PROBLEMS"
FINDING_UNRESOLVED_ROWS = "W12-TILE-ROWS-UNRESOLVED"
FINDING_GATE_RECORD_MISSING = "W12-TILE-GATE-RECORD-MISSING"

#: John's ruling vocabulary, recorded ADDITIVELY on ``parity.john_ruling``
#: at signing (the W9 ``parity.kind`` vocabulary is never rewritten).
RULING_ACCEPTED_LOSS = "accepted-loss"
RULING_EQUIVALENT_SIGNED = "equivalent-signed"
JOHN_RULINGS = (RULING_ACCEPTED_LOSS, RULING_EQUIVALENT_SIGNED)

#: The signature line the gate record must carry once John signs. The W1
#: mockup-amendment gate set the committed pattern ("**Signed by:** John …").
_SIGNED_LINE_RE = re.compile(
    r"^\*\*Signed by:\*\*\s*John\b", re.MULTILINE)
_UNSIGNED_MARK = "UNSIGNED"


def load_gate_record(path: Path | None = None) -> str:
    p = Path(path) if path else GATE_RECORD_PATH
    return p.read_text(encoding="utf-8")


def signature_state(inv: dict | None = None,
                    gate_record_path: Path | None = None) -> dict:
    """Signed iff the inventory flag AND the gate record agree. Fails
    CLOSED: a missing record, a missing flag, or disagreement is unsigned."""
    inv = inv if inv is not None else cso.load_tile_affordance_inventory()
    p = Path(gate_record_path) if gate_record_path else GATE_RECORD_PATH
    if not p.is_file():
        return {"signed": False, "finding": FINDING_GATE_RECORD_MISSING,
                "reason": "the signable gate record is absent: chamber/%s"
                          % p.name}
    text = p.read_text(encoding="utf-8", errors="replace")
    record_signed = bool(_SIGNED_LINE_RE.search(text)) \
        and _UNSIGNED_MARK not in text.splitlines()[0]
    flag_signed = inv.get("signed_by_john") is True
    if record_signed and flag_signed:
        return {"signed": True}
    if record_signed != flag_signed:
        return {"signed": False, "finding": FINDING_UNSIGNED,
                "reason": "signature state disagrees between the inventory "
                          "flag (%r) and the gate record (%r) — a "
                          "half-signed gate fails CLOSED"
                          % (flag_signed, record_signed)}
    return {"signed": False, "finding": FINDING_UNSIGNED,
            "reason": "rail+STATUS parity is not signed by John "
                      "(signed_by_john is false and the gate record "
                      "stands UNSIGNED)"}


def _row_resolution(row: dict) -> dict:
    """One row's retirement resolution:

    * ``resolved-equivalent`` — kind == equivalent (W9's marker checks own
      the liveness proof; :func:`parity_state` folds those problems in);
    * ``ruled`` — a proposed-* row carrying John's additive ruling;
    * ``pending-john`` — a proposed-* row with decision material, awaiting
      the signing;
    * ``undecided`` — anything else (a parity problem by construction).
    """
    parity = row.get("parity") or {}
    kind = parity.get("kind")
    rid = row.get("id") or "?"
    if kind == "equivalent":
        return {"id": rid, "state": "resolved-equivalent", "kind": kind}
    if kind in ("proposed-equivalent", "proposed-loss"):
        ruling = parity.get("john_ruling")
        if ruling in JOHN_RULINGS:
            return {"id": rid, "state": "ruled", "kind": kind,
                    "ruling": ruling}
        return {"id": rid, "state": "pending-john", "kind": kind,
                "decision_material": bool(str(parity.get("note")
                                              or "").strip())}
    return {"id": rid, "state": "undecided", "kind": kind}


def parity_state(inv: dict | None = None, root: Path | None = None) -> dict:
    """The full parity picture: W9's CI gate re-run at the seam (source
    markers still in the tile code; equivalent targets still live) plus the
    per-row retirement resolution."""
    inv = inv if inv is not None else cso.load_tile_affordance_inventory()
    problems = cso.tile_affordance_problems(inv, root=root)
    rows = [_row_resolution(r) for r in (inv.get("rows") or [])]
    pending = [r for r in rows if r["state"] == "pending-john"]
    undecided = [r for r in rows if r["state"] == "undecided"]
    return {
        "problems": problems,
        "rows": rows,
        "row_count": len(rows),
        "pending_john": [r["id"] for r in pending],
        "undecided": [r["id"] for r in undecided],
        "all_rows_resolved": not pending and not undecided and bool(rows),
    }


def retirement_allowed(inv: dict | None = None, *,
                       root: Path | None = None,
                       gate_record_path: Path | None = None) -> dict:
    """THE C11 GATE. ``{"allowed": True}`` only when: the W9 parity checks
    are green, every row is resolved-equivalent or John-ruled, AND the
    parity signature exists (inventory flag + gate record agreeing).
    Otherwise the NAMED refusal — and no caller may delete tile code."""
    inv = inv if inv is not None else cso.load_tile_affordance_inventory()
    par = parity_state(inv, root=root)
    if par["problems"]:
        return {"allowed": False, "finding": FINDING_PARITY_PROBLEMS,
                "problems": par["problems"],
                "reason": "the W9 parity map's own CI gate is not green — "
                          "retirement may only execute against a live map"}
    if not par["all_rows_resolved"]:
        return {"allowed": False, "finding": FINDING_UNRESOLVED_ROWS,
                "pending_john": par["pending_john"],
                "undecided": par["undecided"],
                "reason": "inventory row(s) await John's ruling at the "
                          "signing — every row must map to a live "
                          "rail/STATUS equivalent or a John-signed "
                          "accepted loss"}
    sig = signature_state(inv, gate_record_path=gate_record_path)
    if not sig.get("signed"):
        out = {"allowed": False}
        out.update(sig)
        out["finding"] = sig.get("finding", FINDING_UNSIGNED)
        return out
    return {"allowed": True, "rows": par["rows"]}


def retirement_state(root: Path | None = None) -> dict:
    """The audit-facing rollup: parity + signature + the verdict, as data."""
    inv = cso.load_tile_affordance_inventory()
    par = parity_state(inv, root=root)
    sig = signature_state(inv)
    verdict = retirement_allowed(inv, root=root)
    return {"parity": par, "signature": sig, "verdict": verdict,
            "tiles_stand": not verdict.get("allowed")}
