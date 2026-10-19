"""campaign_seeds — the Campaign's seeds, read one way for the home and the Campaign page.

W3c of the High Seat plan (2026-09-26), as its Rabbit read trimmed it. A seed is a grasscatch receipt on the
Campaign's strip whose why begins "seed:" — the engine's own parked-idea receipt, written through its grasscatch
verb (the import and the say box write them that way). Its stable id is the receipt's index in the strip's
append-only receipts list. A later grasscatch receipt whose why begins "promoted seed <id>" spends it; one whose
why begins "restored seed <id>" gives it back. The engine's receipt kinds are locked (there is no seed kind), so
a seed's fate is said in the same ledger that holds it, by id — never by matching its words.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

SEED = re.compile(r"^\s*seed\s*:\s*", re.I)
PROMOTED = re.compile(r"^\s*promoted seed (s\d+)\b", re.I)
RESTORED = re.compile(r"^\s*restored seed (s\d+)\b", re.I)


def _receipts(folder):
    try:
        d = json.loads((Path(str(folder)) / "strip.json").read_text(encoding="utf-8"))
        return d.get("receipts") or [] if isinstance(d, dict) else []
    except Exception:
        return []


def read_seeds(folder):
    """The seeds that stand — ``[{"id", "text", "at"}]`` in the order they were caught."""
    seeds, spent = {}, {}
    for k, r in enumerate(_receipts(folder)):
        if not isinstance(r, dict) or r.get("kind") != "grasscatch":
            continue
        why = str(r.get("grasscatch_why") or r.get("why") or "")
        m = PROMOTED.match(why)
        if m:
            spent[m.group(1)] = True
            continue
        m = RESTORED.match(why)
        if m:
            spent[m.group(1)] = False
            continue
        if SEED.match(why):
            text = " ".join(str(r.get("deferred") or "").split())
            if text:
                seeds["s%d" % k] = {"id": "s%d" % k, "text": text, "at": str(r.get("as_of") or "")}
    return [s for sid, s in seeds.items() if not spent.get(sid)]


def seed_by_id(folder, seed_id):
    return next((s for s in read_seeds(folder) if s["id"] == str(seed_id or "")), None)
