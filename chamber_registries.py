"""Chamber registries — the wire-homing CI symbol-check + provenance-table
loader/lint (steward-chamber W12, C12).

Both committed registry artifacts under ``chamber/`` name THIS module as
their ``owner_file``:

* ``chamber/wire-homing.json`` — the C12 wire-don't-reinvent registry. Its
  law names ``chamber_registries.lint_wire_homing`` as the CI symbol-check
  that greps each row's owner file(s) for its symbol(s) and fails NAMING
  THE ROW when a symbol moves or vanishes. The registry declared that check
  "active from W1 forward", but no module implemented it before this wave —
  the W12 release bundle ("wire-homing registry symbol-check") lands it and
  ``chamber/W12-AUDIT-REPORT.md`` records the reconciliation honestly.
* ``chamber/provenance-table.json`` — the W1 M1 provenance table (C1/C9
  open read set). This module gives it its owner-side loader and a
  structural lint (versioned, owned, read-set law present, planned cells
  carry grounding + brownfield routes).

Law: READ-ONLY. Never a write, never a spawn, never a network call.
Ecgberht rows resolve against the sibling repo root exactly as the
registry's ``sibling_resolution`` states: env ``ECGBERHT_ROOT`` when set,
else ``<anchor-root>/../Ecgberht`` — never an absolute host path in source.
Stdlib only.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

ANCHOR_ROOT = Path(__file__).resolve().parent
CHAMBER_DIR = ANCHOR_ROOT / "chamber"

WIRE_HOMING_PATH = CHAMBER_DIR / "wire-homing.json"
PROVENANCE_TABLE_PATH = CHAMBER_DIR / "provenance-table.json"

WIRE_HOMING_SCHEMA_VERSION = 1
PROVENANCE_SCHEMA_VERSION = 1

#: The ten wired items the plan's C12 table names. A registry that loses a
#: row (or grows one silently) is a C12 drift the lint names.
EXPECTED_WIRE_ROW_IDS = (
    "run_pulse", "step_detail", "step_note", "status_flip", "compose_first",
    "reflection", "findings_ledger", "live_line", "paced_pty", "auto_commit",
)


def ecgberht_root() -> Path:
    """The sibling engine root — env seam first, then the sibling checkout.
    Same law as ``scripts/run-all-tests.mjs`` (never an absolute host path
    baked into source)."""
    env = os.environ.get("ECGBERHT_ROOT")
    if env:
        return Path(env)
    return ANCHOR_ROOT.parent / "Ecgberht"


def load_wire_homing(path: Path | None = None) -> dict:
    p = Path(path) if path else WIRE_HOMING_PATH
    return json.loads(p.read_text(encoding="utf-8"))


def _repo_root(repo: str, *, anchor_root: Path, ecg_root: Path):
    if repo == "anchor":
        return anchor_root
    if repo == "ecgberht":
        return ecg_root
    return None


def lint_wire_homing(reg: dict | None = None, *,
                     anchor_root: Path | None = None,
                     ecgberht_root_path: Path | None = None) -> list:
    """The C12 CI symbol-check. Empty list == green.

    For every row, every owner file is read and every declared symbol must
    be present VERBATIM (the registry stores grep-verifiable spellings, e.g.
    ``def handle_ecgberht_run_pulse`` / ``export function parseStewardReply``).
    A missing file, a vanished symbol, or a malformed row fails NAMING THE
    ROW — a living registry, never a Phase-0 snapshot.
    """
    problems: list = []
    try:
        reg = reg if reg is not None else load_wire_homing()
    except (OSError, ValueError) as exc:
        return ["wire-homing registry unreadable: %s" % exc]
    a_root = Path(anchor_root) if anchor_root else ANCHOR_ROOT
    e_root = Path(ecgberht_root_path) if ecgberht_root_path else ecgberht_root()

    if reg.get("schema_version") != WIRE_HOMING_SCHEMA_VERSION:
        problems.append("wire-homing: schema_version missing or != %d"
                        % WIRE_HOMING_SCHEMA_VERSION)
    if reg.get("owner_file") != "chamber_registries.py":
        problems.append("wire-homing: owner_file must name "
                        "chamber_registries.py (living-registry law)")

    rows = reg.get("rows")
    if not isinstance(rows, list) or not rows:
        problems.append("wire-homing: rows missing/empty")
        return problems

    seen = []
    for i, row in enumerate(rows):
        rid = str(row.get("id") or "rows[%d]" % i)
        seen.append(row.get("id"))
        owners = row.get("owners")
        if not isinstance(owners, list) or not owners:
            problems.append("%s: no owners — a wired row must name its "
                            "owner file(s) + symbol(s)" % rid)
            continue
        for own in owners:
            repo = own.get("repo")
            root = _repo_root(str(repo), anchor_root=a_root, ecg_root=e_root)
            if root is None:
                problems.append("%s: unknown repo %r (anchor|ecgberht)"
                                % (rid, repo))
                continue
            rel = str(own.get("file") or "")
            symbols = own.get("symbols")
            if not rel or not isinstance(symbols, list) or not symbols:
                problems.append("%s: owner needs file + symbols" % rid)
                continue
            p = root / rel
            if not p.is_file():
                problems.append("%s: owner file does not exist: %s (%s)"
                                % (rid, rel, repo))
                continue
            try:
                text = p.read_text(encoding="utf-8", errors="replace")
            except OSError as exc:
                problems.append("%s: owner file unreadable: %s (%s)"
                                % (rid, rel, exc))
                continue
            for sym in symbols:
                if str(sym) not in text:
                    problems.append(
                        "%s: symbol %r no longer present in %s (%s) — the "
                        "wired seam moved or vanished (C12 kill-branch "
                        "material, never a silent pass)"
                        % (rid, sym, rel, repo))

    missing = [rid for rid in EXPECTED_WIRE_ROW_IDS if rid not in seen]
    if missing:
        problems.append("wire-homing: expected wired row(s) missing from the "
                        "registry: %s" % ", ".join(missing))
    return problems


# ═════════════════════════════════════════════════════════════════════════════
# Provenance table (W1 artifact; this module is its declared owner)
# ═════════════════════════════════════════════════════════════════════════════

def load_provenance_table(path: Path | None = None) -> dict:
    p = Path(path) if path else PROVENANCE_TABLE_PATH
    return json.loads(p.read_text(encoding="utf-8"))


def lint_provenance_table(table: dict | None = None) -> list:
    """Structural lint over the committed provenance table. Empty == green.

    The read-set law's own words bind the planned cells: every cell whose
    store is ``availability=planned`` MUST carry non-empty ``grounding`` and
    ``brownfield`` — a silent drop is a lint failure.
    """
    problems: list = []
    try:
        table = table if table is not None else load_provenance_table()
    except (OSError, ValueError) as exc:
        return ["provenance table unreadable: %s" % exc]
    if table.get("schema_version") != PROVENANCE_SCHEMA_VERSION:
        problems.append("provenance: schema_version missing or != %d"
                        % PROVENANCE_SCHEMA_VERSION)
    if table.get("owner_file") != "chamber_registries.py":
        problems.append("provenance: owner_file must name "
                        "chamber_registries.py")
    if "read_set_law" not in table:
        problems.append("provenance: read_set_law missing")
    stores = table.get("stores")
    cells = table.get("cells")
    if not isinstance(stores, dict) or not stores:
        problems.append("provenance: stores missing/empty")
    if not isinstance(cells, (list, dict)) or not cells:
        problems.append("provenance: cells missing/empty")
        return problems
    cell_iter = cells if isinstance(cells, list) else list(cells.values())
    for i, cell in enumerate(cell_iter):
        if not isinstance(cell, dict):
            problems.append("provenance cells[%d]: not an object" % i)
            continue
        cid = str(cell.get("id") or cell.get("element") or "cells[%d]" % i)
        store = cell.get("store")
        if store and isinstance(stores, dict) and store not in stores:
            problems.append("%s: names unknown store %r" % (cid, store))
        if str(cell.get("availability") or "") == "planned":
            for key in ("grounding", "brownfield"):
                if not str(cell.get(key) or "").strip():
                    problems.append(
                        "%s: availability=planned without non-empty %r — "
                        "the read-set law forbids the silent drop"
                        % (cid, key))
    return problems
