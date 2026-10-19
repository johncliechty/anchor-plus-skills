"""The roadmap_events DENY assertion + spine-write guard (steward-chamber W4).

``roadmap_events`` keeps exactly ONE writer, NAMED: Ecgberht
``engine/roadmap.mjs :: appendRoadmapEvent / appendRoadmapEventDurable``.
This module is the STATIC half of that law: :func:`scan_roadmap_event_appends`
sweeps BOTH trees' chamber/bridge sources and fails — naming file, line and
pattern — any source that appends ``roadmap_events`` (mutation of the events
list, or a direct write of the roadmap store file) outside the sole writer.
The RUNTIME half is the W4 zero-spine-write test, which drives the chamber
code paths against a fixture spine and asserts byte-identical spine files
afterward (:func:`spine_fingerprint` is its measuring stick).

READS ARE NOT WRITES: the chamber reads ``roadmap.json`` freely (roadmap IS
in the open read set); only mutation verbs and store-file writes are denied.

SCOPE — the chamber/bridge source surface, per the plan:
* Anchor: the root-level product ``*.py`` modules + ``static/*.js``
  (tests/fixtures are not product sources and are out of scope);
* Ecgberht: ``engine/**/*.mjs`` + ``scripts/**/*.mjs``.

EXEMPT, by name and for a stated reason:
* ``engine/roadmap.mjs`` — IS the named sole writer;
* ``chamber_spine_guard.py`` — carries the deny patterns as literals.

Stdlib only. The sibling resolves via ``ECGBERHT_ROOT`` env else the checkout
beside this tree — never an absolute host path.
"""
from __future__ import annotations

import hashlib
import os
import re
from pathlib import Path

ANCHOR_ROOT = Path(__file__).resolve().parent

#: The named sole writer (the ONLY source allowed to append roadmap_events).
SOLE_WRITER = "engine/roadmap.mjs"
SOLE_WRITER_SYMBOLS = ("appendRoadmapEvent", "appendRoadmapEventDurable")

#: Exempt sources: (relative path suffix, reason).
EXEMPT = (
    (SOLE_WRITER, "the named sole writer of roadmap_events"),
    ("chamber_spine_guard.py",
     "this guard — it carries the deny patterns as string literals"),
)

#: Deny patterns. Each catches an APPEND/mutation, never a read.
DENY_PATTERNS = (
    ("events-mutation",
     re.compile(r"\broadmap_events\s*\.\s*"
                r"(?:push|unshift|splice|pop|shift|append|extend|insert)"
                r"\s*\(")),
    ("events-key-mutation",
     re.compile(r"\[\s*['\"]roadmap_events['\"]\s*\]\s*"
                r"(?:\.\s*(?:append|extend|insert)\s*\(|=(?!=))")),
    ("events-assignment",
     re.compile(r"\broadmap_events\s*=(?!=)")),
)

#: A line writing the roadmap store file directly (outside the sole writer)
#: is an append by other means. Both tokens must sit on ONE line.
STORE_FILE_TOKEN = re.compile(r"roadmap\.json")
STORE_WRITE_VERBS = re.compile(
    r"write_text|write_bytes|json\.dump|os\.replace|"
    r"writeFileSync|writeFile\(|appendFile|writeFileAtomic|createWriteStream")


def ecgberht_root() -> Path:
    env = os.environ.get("ECGBERHT_ROOT", "").strip()
    if env:
        return Path(env)
    return ANCHOR_ROOT.parent / "Ecgberht"


def _is_exempt(rel: str) -> bool:
    norm = rel.replace("\\", "/")
    return any(norm.endswith(suffix) for suffix, _reason in EXEMPT)


def _chamber_bridge_sources(anchor_root: Path, ecg_root: Path):
    """(tree, relative-path, absolute-path) for every in-scope source."""
    out = []
    if anchor_root.is_dir():
        for p in sorted(anchor_root.glob("*.py")):
            out.append(("anchor", p.name, p))
        static = anchor_root / "static"
        if static.is_dir():
            for p in sorted(static.glob("*.js")):
                out.append(("anchor", "static/" + p.name, p))
    if ecg_root.is_dir():
        for sub in ("engine", "scripts"):
            base = ecg_root / sub
            if not base.is_dir():
                continue
            for p in sorted(base.rglob("*.mjs")):
                rel = sub + "/" + p.relative_to(base).as_posix()
                out.append(("ecgberht", rel, p))
    return out


def scan_roadmap_event_appends(anchor_root: Path | None = None,
                               ecgberht_root_path: Path | None = None) -> list:
    """The DENY scan. Returns ``[{tree, file, line, pattern, excerpt}, ...]``
    — empty means the single-writer law holds across both trees. Roots are
    injectable so the bite-tests can prove the scan catches an offender."""
    anchor_root = Path(anchor_root) if anchor_root else ANCHOR_ROOT
    ecg_root = (Path(ecgberht_root_path) if ecgberht_root_path
                else ecgberht_root())
    violations = []
    for tree, rel, p in _chamber_bridge_sources(anchor_root, ecg_root):
        if _is_exempt(rel):
            continue
        try:
            text = p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for lineno, line in enumerate(text.splitlines(), 1):
            for name, pat in DENY_PATTERNS:
                if pat.search(line):
                    violations.append({
                        "tree": tree, "file": rel, "line": lineno,
                        "pattern": name, "excerpt": line.strip()[:160]})
            if STORE_FILE_TOKEN.search(line) and STORE_WRITE_VERBS.search(line):
                violations.append({
                    "tree": tree, "file": rel, "line": lineno,
                    "pattern": "store-file-write",
                    "excerpt": line.strip()[:160]})
    return violations


def deny_problems(anchor_root: Path | None = None,
                  ecgberht_root_path: Path | None = None) -> list:
    """Flatten the scan into failure strings naming file + line + pattern."""
    return [
        "%(tree)s %(file)s:%(line)d [%(pattern)s] %(excerpt)s" % v
        for v in scan_roadmap_event_appends(anchor_root, ecgberht_root_path)]


def sole_writer_present(ecgberht_root_path: Path | None = None) -> dict:
    """The law needs its writer: assert engine/roadmap.mjs still exports the
    named append symbols (a moved/renamed sole writer would make the DENY
    scan vacuously green)."""
    root = (Path(ecgberht_root_path) if ecgberht_root_path
            else ecgberht_root())
    p = root / SOLE_WRITER
    if not p.is_file():
        return {"ok": False, "missing": SOLE_WRITER}
    text = p.read_text(encoding="utf-8", errors="replace")
    absent = [s for s in SOLE_WRITER_SYMBOLS
              if not re.search(r"export\s+function\s+%s\b" % re.escape(s),
                               text)]
    return {"ok": not absent, "missing_symbols": absent}


# ── Runtime measuring stick (the W4 zero-spine-write tests) ─────────────────

#: The spine surfaces chamber code must never write: the roadmap store
#: (roadmap_events + receipts persisted as events) and the .ecgberht stores
#: (insession run receipts, status outbox, attention, reflection payloads).
SPINE_RELS = ("roadmap.json", ".ecgberht")


def spine_fingerprint(folder) -> dict:
    """``{relative-path: sha256}`` over every spine file under ``folder``.
    Taken before and after driving chamber code, an equal fingerprint IS the
    zero-spine-write assertion (receipt schema / reflection payloads /
    roadmap_events all untouched)."""
    folder = Path(folder)
    out = {}
    for rel in SPINE_RELS:
        p = folder / rel
        if p.is_file():
            out[rel] = hashlib.sha256(p.read_bytes()).hexdigest()
        elif p.is_dir():
            for f in sorted(p.rglob("*")):
                if f.is_file():
                    key = rel + "/" + f.relative_to(p).as_posix()
                    out[key] = hashlib.sha256(f.read_bytes()).hexdigest()
    return out
