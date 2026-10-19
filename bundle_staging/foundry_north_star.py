"""Skill Foundry v2 — Wave 8: the sanctioned per-skill North-Star mutation
path + the out-of-band drift gates.

A skill's ``NORTH-STAR.md`` is its locked objective — the anti-drift anchor
its changes are gated against. Wave 8 makes ``foundry.edit_north_star`` the
ONLY sanctioned way that file changes:

* **proposal-diff** — :func:`propose_edit` computes a unified diff of the
  current North Star against the proposed text and PARKS it as a proposal
  artifact under the control-plane home. Nothing on the skill is touched.
* **explicit human confirm** — a proposal applies only through the Wave-3
  runner's mutate gate (single-use confirm token + declared write scope);
  the dispatch surface is ``foundry_ops`` — this module never bypasses it.
* **apply as a branch commit with the prior version retained** —
  :func:`apply_edit` REFUSES when the file changed since the proposal (a
  stale approval is no approval — the human never saw the new base), RETAINS
  the prior version in ``north-star-history/`` next to a hash LEDGER, and
  writes the new text atomically. The git branch commit belongs to the op
  layer (DR-02: mutations apply on a branch, never straight to main).

The drift gates (the Wave-8 done-when's second clause):

* :func:`gate_ledger` — the RUNTIME gate, driven from map.json v2: every
  map skill whose North Star is ledger-tracked must hash to the ledger's
  recorded head. A direct out-of-band write (someone editing NORTH-STAR.md
  without the op) FAILS the gate by name (``out-of-band-write``); a deleted
  tracked file fails too. Skills with no ledger yet (pre-Wave-8 material)
  are counted honestly as untracked — the gate cannot attest what was never
  registered, and says so rather than fabricating a verdict.
* :func:`gate_source` — the GREP gate (the Wave-2 pattern): no product
  module outside the sanctioned writers may put a ``NORTH-STAR.md`` write on
  a line. The sanctioned writers are this module (the mutation core) and
  ``foundry_ops`` (the scaffold writes the initial stub).

Stdlib only (Anchor's no-dep rule) + the product seams ``foundry_decisions``
/ ``foundry_map`` / ``foundry_map_gates``.
"""

import difflib
import hashlib
import json
import os
import re
import time
import uuid
from pathlib import Path

import foundry_decisions as _fd
import foundry_map as _fm
import foundry_map_gates as _fg


# ── Constants ────────────────────────────────────────────────────────────────

NORTH_STAR_FILENAME = "NORTH-STAR.md"

#: Retained prior versions + the hash ledger live INSIDE the skill dir, so
#: they ride the same branch commits as the file they attest.
HISTORY_DIRNAME = "north-star-history"
LEDGER_FILENAME = "ledger.json"
LEDGER_SCHEMA_ID = "foundry-north-star-ledger/v1"

#: Parked proposals (the middle state of the propose → confirm → apply
#: round-trip) live under the control-plane home, keyed by proposal id.
PROPOSALS_DIRNAME = "north_star_proposals"
PROPOSAL_SCHEMA_ID = "foundry-north-star-proposal/v1"
_PROPOSAL_ID_RE = re.compile(r"^nsp-[0-9a-f]{32}$")

#: Ledger entry actions.
ACTION_SCAFFOLD = "scaffold"
ACTION_APPLY = "apply"

#: Gate names (the Wave-8 pair, beside the Wave-6 DRIFT_GATES trio).
GATE_LEDGER = "north-star-ledger"
GATE_SOURCE = "north-star-source"

#: The ONLY product modules allowed to put a NORTH-STAR.md write on a line:
#: this module (the mutation core) and foundry_ops (the scaffold writes the
#: initial stub; the ops are the dispatch surface).
SANCTIONED_WRITERS = ("foundry_north_star.py", "foundry_ops.py")

#: Same-line write indicators for the grep gate (the Wave-2 pattern).
_WRITE_MARKERS = ("open(", "write_text", "write_bytes", "writelines",
                  "os.replace", ".write(", "_atomic_write(", "shutil.copy")

#: Wave-1 anti-drift convention: the mutation path traces to the North Star.
TRACES_TO_NORTH_STAR = (_fd.NS_GUI_DRIVES_REAL_MACHINERY,)


# ── Paths / small helpers ────────────────────────────────────────────────────

def north_star_path(skill_dir) -> Path:
    return Path(skill_dir) / NORTH_STAR_FILENAME


def history_dir(skill_dir) -> Path:
    return Path(skill_dir) / HISTORY_DIRNAME


def ledger_path(skill_dir) -> Path:
    return history_dir(skill_dir) / LEDGER_FILENAME


def read_north_star(skill_dir) -> str:
    """The current North-Star text (``""`` when the file does not exist)."""
    try:
        return north_star_path(skill_dir).read_text(encoding="utf-8")
    except OSError:
        return ""


def sha256_text(text) -> str:
    return hashlib.sha256(str(text).encode("utf-8")).hexdigest()


def _atomic_write(path: Path, text: str) -> None:
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(str(tmp), str(path))


# ── The hash ledger (what the runtime drift gate attests against) ────────────

def _load_or_new_ledger(skill_dir) -> dict:
    lp = ledger_path(skill_dir)
    if lp.is_file():
        try:
            ledger = json.loads(lp.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            ledger = None
        if isinstance(ledger, dict) and isinstance(ledger.get("entries"),
                                                   list):
            return ledger
    return {"schema": LEDGER_SCHEMA_ID, "current_sha256": None, "entries": []}


def record_version(skill_dir, *, action, proposal_id=None,
                   prior_rel=None) -> dict:
    """Record the CURRENT on-disk North Star as the ledger head → the entry.

    Called by the scaffold (the baseline — a scaffolded skill is tracked from
    birth) and by :func:`apply_edit` (every sanctioned edit). Hashes exactly
    what is on disk — never a caller-supplied string — so the ledger can only
    attest real file states."""
    skill_dir = Path(skill_dir)
    ledger = _load_or_new_ledger(skill_dir)
    entry = {
        "seq": len(ledger["entries"]) + 1,
        "action": str(action),
        "sha256": sha256_text(read_north_star(skill_dir)),
        "proposal_id": proposal_id,
        "prior_rel": prior_rel,
        "ts": round(time.time(), 3),
    }
    ledger["entries"].append(entry)
    ledger["current_sha256"] = entry["sha256"]
    hdir = history_dir(skill_dir)
    hdir.mkdir(parents=True, exist_ok=True)
    _atomic_write(ledger_path(skill_dir),
                  json.dumps(ledger, indent=2, ensure_ascii=False) + "\n")
    return entry


# ── Propose → load → apply (the round-trip core) ─────────────────────────────

def propose_edit(skill, skill_dir, new_text, *, proposals_home) -> dict:
    """Park a proposal: the unified diff of current → proposed.

    Touches ONLY the proposals home — the skill's North Star is not written
    here. A proposal identical to the current text refuses honestly (there
    is nothing to confirm)."""
    skill = str(skill)
    base = read_north_star(skill_dir)
    new_text = str(new_text)
    if new_text == base:
        return {"ok": False, "reason": "proposal-no-change"}
    diff = "".join(difflib.unified_diff(
        base.splitlines(keepends=True), new_text.splitlines(keepends=True),
        fromfile="%s (current)" % NORTH_STAR_FILENAME,
        tofile="%s (proposed)" % NORTH_STAR_FILENAME))
    proposal_id = "nsp-" + uuid.uuid4().hex
    record = {
        "schema": PROPOSAL_SCHEMA_ID,
        "proposal_id": proposal_id,
        "skill": skill,
        "skill_dir": str(Path(skill_dir)),
        "base_sha256": sha256_text(base),
        "new_text": new_text,
        "diff": diff,
        "created_ts": round(time.time(), 3),
    }
    home = Path(proposals_home)
    home.mkdir(parents=True, exist_ok=True)
    _atomic_write(home / (proposal_id + ".json"),
                  json.dumps(record, indent=2, ensure_ascii=False) + "\n")
    return {"ok": True, "proposal_id": proposal_id, "diff": diff,
            "base_sha256": record["base_sha256"]}


def load_proposal(proposal_id, *, proposals_home):
    """Load a parked proposal → dict, or ``None``.

    The id is path material crossing a payload trust boundary, so anything
    off the ``nsp-<hex32>`` pattern is refused outright, never joined."""
    pid = str(proposal_id or "")
    if not _PROPOSAL_ID_RE.match(pid):
        return None
    try:
        record = json.loads((Path(proposals_home) / (pid + ".json"))
                            .read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return record if isinstance(record, dict) else None


def apply_edit(skill_dir, proposal) -> dict:
    """Apply a parked proposal to the skill's North Star — prior RETAINED.

    Refuses (honestly, without writing) when the on-disk file no longer
    hashes to the proposal's base: the file changed since the human saw the
    diff, so the approval does not transfer. On apply: the prior version is
    copied into ``north-star-history/`` (when there was one), the new text
    lands atomically, and the ledger head moves. The branch commit belongs
    to the op layer (``foundry_ops.edit_north_star``)."""
    skill_dir = Path(skill_dir)
    current = read_north_star(skill_dir)
    if sha256_text(current) != str(proposal.get("base_sha256") or ""):
        return {"ok": False, "reason": "north-star-changed-since-proposal"}
    ledger = _load_or_new_ledger(skill_dir)
    seq = len(ledger["entries"]) + 1
    prior_rel = None
    if current:
        prior_name = "NORTH-STAR-%03d.md" % seq
        hdir = history_dir(skill_dir)
        hdir.mkdir(parents=True, exist_ok=True)
        _atomic_write(hdir / prior_name, current)
        prior_rel = HISTORY_DIRNAME + "/" + prior_name
    new_text = str(proposal.get("new_text") or "")
    _atomic_write(north_star_path(skill_dir), new_text)
    
    # Wave 10: update the skill integrity manifest atomically
    try:
        import foundry_integrity
        foundry_integrity.update_manifest_entry(skill_dir.name, "NORTH-STAR.md", new_text)
    except Exception as e:
        import logging
        logging.getLogger("foundry_north_star").warning("failed to update manifest entry: %s", e)
        
    entry = record_version(skill_dir, action=ACTION_APPLY,
                           proposal_id=proposal.get("proposal_id"),
                           prior_rel=prior_rel)
    return {"ok": True, "sha256": entry["sha256"],
            "prior_retained": prior_rel, "entry": entry}


# ── The runtime drift gate (ledger vs. disk, driven from map.json v2) ────────

def verify_north_star(skill_dir) -> dict:
    """One skill's drift check → ``{"tracked", "ok", "reason"}``.

    ``tracked=False`` (no ledger yet) is honest-untracked, not a failure —
    the gate cannot attest what was never registered. A tracked skill fails
    on an unreadable ledger, a deleted North Star, or a file that no longer
    hashes to the recorded head (the out-of-band write)."""
    lp = ledger_path(skill_dir)
    if not lp.is_file():
        return {"tracked": False, "ok": True, "reason": "untracked"}
    try:
        ledger = json.loads(lp.read_text(encoding="utf-8"))
        head = ledger["current_sha256"]
    except (OSError, ValueError, KeyError, TypeError):
        return {"tracked": True, "ok": False, "reason": "ledger-unreadable"}
    if not north_star_path(skill_dir).is_file():
        return {"tracked": True, "ok": False, "reason": "north-star-deleted"}
    if sha256_text(read_north_star(skill_dir)) != head:
        return {"tracked": True, "ok": False, "reason": "out-of-band-write"}
    return {"tracked": True, "ok": True, "reason": None}


def gate_ledger(map_doc=None, root=None) -> dict:
    """The runtime drift gate over every map.json-v2 skill on disk.

    Red iff any tracked North Star drifted from its ledger head. A source
    dir absent from disk is skipped here — on-disk existence is the Wave-6
    target-existence gate's job, not this gate's."""
    if map_doc is None:
        map_doc = _fm.load_map()
    skills = map_doc.get("skills") if isinstance(map_doc, dict) else None
    if not isinstance(skills, list):
        return {"gate": GATE_LEDGER, "ok": False,
                "problems": ["map-not-an-object"], "checked": 0, "tracked": 0}
    base = _fg._foundry_root(root)
    problems = []
    checked = tracked = 0
    for skill in skills:
        if not isinstance(skill, dict):
            continue
        ref = skill.get("ref") if isinstance(skill.get("ref"), str) else "?"
        d = _fg._source_dir(skill.get("source") or "", base)
        if not d.is_dir():
            continue
        checked += 1
        v = verify_north_star(d)
        if v["tracked"]:
            tracked += 1
        if not v["ok"]:
            problems.append("north-star-drift:%s:%s" % (ref, v["reason"]))
    return {"gate": GATE_LEDGER, "ok": not problems, "problems": problems,
            "checked": checked, "tracked": tracked}


# ── The source grep gate (no out-of-band writer in product code) ─────────────

def scan_out_of_band_writers(root=None, allowed=SANCTIONED_WRITERS) -> list:
    """Grep the product modules for out-of-band NORTH-STAR.md write lines.

    The Wave-2 pattern: a write marker on the SAME LINE as the per-skill
    North-Star filename, in any root product module outside the sanctioned
    writers, is an out-of-band mutation path → one offender row per line.
    Scans ``<root>/*.py`` (the product modules live at the build root; tests
    are not product code)."""
    base = Path(root) if root else Path(__file__).resolve().parent
    offenders = []
    for py in sorted(base.glob("*.py")):
        if py.name in allowed:
            continue
        try:
            src = py.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for n, line in enumerate(src.splitlines(), start=1):
            if NORTH_STAR_FILENAME in line and any(
                    w in line for w in _WRITE_MARKERS):
                offenders.append("%s:%d:%s" % (py.name, n, line.strip()[:160]))
    return offenders


def gate_source(root=None, allowed=SANCTIONED_WRITERS) -> dict:
    problems = ["out-of-band-north-star-writer:%s" % o
                for o in scan_out_of_band_writers(root, allowed)]
    return {"gate": GATE_SOURCE, "ok": not problems, "problems": problems}


def run_north_star_gates(map_doc=None, *, root=None, source_root=None) -> dict:
    """Both Wave-8 gates → ``{"ok": all-green, "gates": [...]}`` (the Wave-6
    ``run_drift_gates`` shape, so callers compose them uniformly)."""
    gates = [gate_ledger(map_doc, root=root), gate_source(source_root)]
    return {"ok": all(g["ok"] for g in gates), "gates": gates}
