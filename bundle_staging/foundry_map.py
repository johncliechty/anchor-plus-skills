"""Skill Foundry v2 — Wave 5: map.json v2 schema + the resolved-graph lockfile.

``map.json`` v1 (the Skill Foundry root) is a flat pointer list whose
relationships live in free-prose ``note`` fields — "jumper COMPOSES gandalf",
"crucible IMPORTS Foreman's libs" are strings no machine can check. This
module is the v2 contract, ANCHOR-SIDE and worktree-local (single-source: the
foundry's own tree is never edited from this build):

* **typed edges** — every relationship is a machine-readable edge carrying
  exactly ONE ``type`` from the closed enum ``compose | import | augment``,
  keyed by the target's STABLE ``ref`` (``skill:<slug>`` — the identity that
  survives a display-name or folder rename). An UNTYPED edge (no ``type``),
  an OVERLOADED edge (a list of types, or a ``types`` key), an out-of-enum
  type, a dangling target, a self-edge, or a duplicate (type, target) pair
  FAILS validation.
* **closed-enum status** — the PyPI Development-Status trove ladder
  (``1 - Planning`` … ``7 - Inactive``); anything else fails.
* **tier + semver** — each skill records the runner's model tier (the same
  ``heavy | standard`` vocabulary as ``skill_runner.TIERS``) and an exact
  semver ``version``; edges declare semver RANGES (the manifest-range side).
* **resolved-graph lockfile** — the Cargo.lock analogue
  (``foundry_map_v2.lock.json``): ranges live in the map, the lockfile pins
  every edge to the exact resolved target version AND pins each skill's full
  TRANSITIVE closure — deterministically (sorted, no timestamps), so Wave 6
  can regenerate + ``git diff --exit-code`` it and couple signing/checksums
  to it.

Single-source discipline: the closed enums, patterns, and allowed/required
key sets live ONLY in the JSON Schema document
(``foundry_map_v2.schema.json``); this validator READS them from the schema
at import time, so the schema artifact and the Python checks cannot drift.

Stdlib only (Anchor's no-dep rule: json/re/pathlib) + the Wave-1 decision
module for the North-Star trace.
"""

import json
import re
from pathlib import Path

import foundry_decisions as _fd


# ── Constants / worktree-local artifacts ─────────────────────────────────────

_MODULE_DIR = Path(__file__).resolve().parent

#: The three Wave-5 artifacts (all worktree-local Python/JSON — the foundry's
#: own map.json v1 is never touched by this build).
SCHEMA_FILE = _MODULE_DIR / "foundry_map_v2.schema.json"
MAP_FILE = _MODULE_DIR / "foundry_map_v2.json"
LOCK_FILE = _MODULE_DIR / "foundry_map_v2.lock.json"

MAP_SCHEMA_ID = "foundry-map/v2"
MAP_VERSION = 2
LOCK_SCHEMA_ID = "foundry-map-lock/v1"
LOCK_VERSION = 1

#: The map IS the knowledge-graph library's data layer (Wave-1 convention:
#: every foundry-v2 artifact traces to a locked North-Star clause).
TRACES_TO_NORTH_STAR = (_fd.NS_KNOWLEDGE_GRAPH,)


def load_schema(path=None) -> dict:
    """Load the JSON Schema document (the enums' single source)."""
    raw = Path(path or SCHEMA_FILE).read_text(encoding="utf-8")
    schema = json.loads(raw)
    if "definitions" not in schema or "properties" not in schema:
        raise ValueError("foundry-map schema document is malformed")
    return schema


#: The schema loads ONCE at import; a missing/broken schema artifact breaks
#: every consumer loudly (never a silent fallback to hard-coded enums).
_SCHEMA = load_schema()
_DEFS = _SCHEMA["definitions"]

#: Closed enums + patterns, read FROM the schema (never re-declared here).
EDGE_TYPES = tuple(_DEFS["edge_type"]["enum"])
STATUS_LADDER = tuple(_DEFS["status"]["enum"])
TIERS = tuple(_DEFS["tier"]["enum"])
_REF_RE = re.compile(_DEFS["ref"]["pattern"])
_SEMVER_RE = re.compile(_DEFS["semver"]["pattern"])

#: Allowed/required key sets, also read FROM the schema.
_TOP_ALLOWED = frozenset(_SCHEMA["properties"])
_TOP_REQUIRED = tuple(_SCHEMA["required"])
_SKILL_ALLOWED = frozenset(_DEFS["skill"]["properties"])
_SKILL_REQUIRED = tuple(_DEFS["skill"]["required"])
_EDGE_ALLOWED = frozenset(_DEFS["edge"]["properties"])
_EDGE_REQUIRED = tuple(_DEFS["edge"]["required"])


# ── Semver (exact versions + manifest ranges) ────────────────────────────────

def parse_semver(text):
    """``'1.2.3'`` → ``(1, 2, 3)``; raises ``ValueError`` on anything else."""
    m = _SEMVER_RE.match(str(text).strip())
    if not m:
        raise ValueError("not-semver:%r" % (text,))
    return tuple(int(g) for g in m.groups())


def _caret_upper(v):
    """npm caret semantics: the first non-zero component may not change."""
    major, minor, patch = v
    if major > 0:
        return (major + 1, 0, 0)
    if minor > 0:
        return (0, minor + 1, 0)
    return (0, 0, patch + 1)


def _tilde_upper(v):
    return (v[0], v[1] + 1, 0)


#: Comparator operators, longest first (``>=`` must win over ``>``).
_OPS = (">=", "<=", "==", "!=", ">", "<", "=")


def parse_range(text):
    """Parse a semver RANGE into ``[(op, version), ...]`` AND-clauses.

    Grammar (kept deliberately small, stdlib-only): ``*`` (any), exact
    (``1.2.3`` / ``=1.2.3`` / ``==1.2.3``), comparators (``>= > <= < !=``),
    caret (``^1.2.0``), tilde (``~1.2.3``); clauses separated by spaces or
    commas are ANDed. Raises ``ValueError`` on an unparseable clause."""
    parts = [p for p in re.split(r"[,\s]+", str(text).strip()) if p]
    if not parts:
        raise ValueError("empty-range")
    clauses = []
    for part in parts:
        if part == "*":
            clauses.append(("*", None))
        elif part.startswith("^"):
            v = parse_semver(part[1:])
            clauses.append((">=", v))
            clauses.append(("<", _caret_upper(v)))
        elif part.startswith("~"):
            v = parse_semver(part[1:])
            clauses.append((">=", v))
            clauses.append(("<", _tilde_upper(v)))
        else:
            for op in _OPS:
                if part.startswith(op):
                    clauses.append((op if op != "=" else "==",
                                    parse_semver(part[len(op):])))
                    break
            else:
                clauses.append(("==", parse_semver(part)))
    return clauses


def range_satisfied(version, range_text) -> bool:
    """True iff ``version`` (exact semver) satisfies every clause of the range."""
    v = parse_semver(version)
    for op, rv in parse_range(range_text):
        if op == "*":
            continue
        if op == ">=" and not v >= rv:
            return False
        if op == "<=" and not v <= rv:
            return False
        if op == ">" and not v > rv:
            return False
        if op == "<" and not v < rv:
            return False
        if op == "==" and v != rv:
            return False
        if op == "!=" and v == rv:
            return False
    return True


# ── The validator (returns a problem list; empty = valid) ────────────────────

def _validate_edge(owner, eidx, edge, seen_pairs):
    out = []
    where = "%s:edges[%d]" % (owner, eidx)
    if not isinstance(edge, dict):
        return ["%s:not-an-object" % where]
    if "types" in edge:
        out.append("%s:edge-overloaded:types-key" % where)
    etype = edge.get("type")
    if "type" not in edge:
        out.append("%s:edge-untyped" % where)
    elif isinstance(etype, (list, tuple)):
        out.append("%s:edge-overloaded:%r" % (where, etype))
    elif etype not in EDGE_TYPES:
        out.append("%s:edge-type-out-of-enum:%r" % (where, etype))
    for key in _EDGE_REQUIRED:
        if key != "type" and key not in edge:
            out.append("%s:missing-key:%s" % (where, key))
    for key in edge:
        if key not in _EDGE_ALLOWED and key != "types":
            out.append("%s:unknown-key:%s" % (where, key))
    to = edge.get("to")
    if "to" in edge and (not isinstance(to, str) or not _REF_RE.match(to)):
        out.append("%s:edge-to-not-a-stable-ref:%r" % (where, to))
    if "range" in edge:
        rng = edge["range"]
        if not isinstance(rng, str) or not rng.strip():
            out.append("%s:edge-range-empty" % where)
        else:
            try:
                parse_range(rng)
            except ValueError as exc:
                out.append("%s:edge-range-invalid:%s" % (where, exc))
    if "note" in edge and not isinstance(edge["note"], str):
        out.append("%s:note-not-a-string" % where)
    if isinstance(etype, str) and isinstance(to, str):
        pair = (etype, to)
        if pair in seen_pairs:
            out.append("%s:edge-duplicate:%s->%s" % (where, etype, to))
        seen_pairs.add(pair)
    return out


def _validate_skill(idx, skill, refs):
    out = []
    label = "skills[%d]" % idx
    if not isinstance(skill, dict):
        return ["%s:not-an-object" % label]
    ref = skill.get("ref")
    if isinstance(ref, str) and ref:
        label = ref
    for key in _SKILL_REQUIRED:
        if key not in skill:
            out.append("%s:missing-key:%s" % (label, key))
    for key in skill:
        if key not in _SKILL_ALLOWED:
            out.append("%s:unknown-key:%s" % (label, key))
    if "ref" in skill:
        if not isinstance(ref, str) or not _REF_RE.match(ref or ""):
            out.append("%s:ref-not-stable:%r" % (label, ref))
        elif ref in refs:
            out.append("duplicate-ref:%s" % ref)
        else:
            refs[ref] = idx
    for key in ("name", "source"):
        if key in skill and (not isinstance(skill[key], str)
                             or not skill[key].strip()):
            out.append("%s:%s-empty" % (label, key))
    if "status" in skill and skill["status"] not in STATUS_LADDER:
        out.append("%s:status-out-of-enum:%r" % (label, skill["status"]))
    if "tier" in skill and skill["tier"] not in TIERS:
        out.append("%s:tier-out-of-enum:%r" % (label, skill["tier"]))
    if "version" in skill:
        v = skill["version"]
        if not isinstance(v, str) or not _SEMVER_RE.match(v):
            out.append("%s:version-not-semver:%r" % (label, v))
    if "note" in skill and not isinstance(skill["note"], str):
        out.append("%s:note-not-a-string" % label)
    edges = skill.get("edges")
    if "edges" in skill and not isinstance(edges, list):
        out.append("%s:edges-not-a-list" % label)
        edges = None
    seen_pairs = set()
    for eidx, edge in enumerate(edges or ()):
        out.extend(_validate_edge(label, eidx, edge, seen_pairs))
    return out


def validate_map(doc) -> list:
    """Validate a map.json v2 document → list of problems (empty = valid).

    Enforces the JSON Schema's structural contract (enums, patterns, key
    sets — read FROM the schema document) plus the cross-document rules a
    JSON Schema cannot express: ref uniqueness, edge-target existence
    within the map, and no self-edges."""
    if not isinstance(doc, dict):
        return ["map-not-an-object"]
    problems = []
    for key in _TOP_REQUIRED:
        if key not in doc:
            problems.append("missing-top-level-key:%s" % key)
    for key in doc:
        if key not in _TOP_ALLOWED:
            problems.append("unknown-top-level-key:%s" % key)
    if "schema" in doc and doc["schema"] != MAP_SCHEMA_ID:
        problems.append("schema-id-wrong:%r" % (doc["schema"],))
    if "map_version" in doc and doc["map_version"] != MAP_VERSION:
        problems.append("map-version-wrong:%r" % (doc["map_version"],))
    skills = doc.get("skills")
    if not isinstance(skills, list) or not skills:
        problems.append("skills-missing-or-empty")
        return problems
    refs = {}
    for idx, skill in enumerate(skills):
        problems.extend(_validate_skill(idx, skill, refs))
    # Referential integrity: every edge target resolves to a ref IN the map
    # (Wave 6 adds the on-disk target-existence gate on top of this).
    for skill in skills:
        if not isinstance(skill, dict):
            continue
        src = skill.get("ref")
        label = src if isinstance(src, str) and src else "?"
        for edge in (skill.get("edges") if isinstance(skill.get("edges"),
                                                      list) else ()) or ():
            if not isinstance(edge, dict):
                continue
            to = edge.get("to")
            if not isinstance(to, str) or not _REF_RE.match(to):
                continue  # already flagged by the edge validator
            if to == src:
                problems.append("edge-self:%s" % label)
            elif to not in refs:
                problems.append("edge-target-unknown:%s->%s" % (label, to))
    return problems


# ── Resolution: pin ranges + transitive closure (the lockfile's substance) ───

def resolve_graph(doc):
    """Resolve a VALID map into the pinned graph → ``(resolved, problems)``.

    ``resolved`` maps each ref to ``{ref, name, version, source,
    dependencies, closure}`` where every dependency is pinned to the exact
    resolved target version and ``closure`` is the full TRANSITIVE closure
    as sorted ``ref@version`` pins. Any problem (validation failure, a range
    the target's declared version does not satisfy, a dependency cycle)
    yields ``(None, problems)`` — never a partial or fabricated graph."""
    problems = validate_map(doc)
    if problems:
        return None, problems
    by_ref = {s["ref"]: s for s in doc["skills"]}
    for skill in doc["skills"]:
        for edge in skill["edges"]:
            target = by_ref[edge["to"]]
            if not range_satisfied(target["version"], edge["range"]):
                problems.append(
                    "edge-range-unsatisfied:%s->%s:declared %r, target is %s"
                    % (skill["ref"], edge["to"], edge["range"],
                       target["version"]))
    # Cycle check over ALL edge types — a pinned closure needs a DAG.
    _GRAY, _BLACK = 1, 2
    state = {}

    def _visit(ref, chain):
        state[ref] = _GRAY
        for edge in by_ref[ref]["edges"]:
            to = edge["to"]
            if state.get(to) == _GRAY:
                cycle = chain[chain.index(to):] + [to]
                problems.append("edge-cycle:%s" % "->".join(cycle))
            elif state.get(to) != _BLACK:
                _visit(to, chain + [to])
        state[ref] = _BLACK

    for ref in sorted(by_ref):
        if state.get(ref) != _BLACK:
            _visit(ref, [ref])
    if problems:
        return None, problems
    closure_cache = {}

    def _closure(ref):
        if ref not in closure_cache:
            acc = set()
            for edge in by_ref[ref]["edges"]:
                to = edge["to"]
                acc.add("%s@%s" % (to, by_ref[to]["version"]))
                acc |= _closure(to)
            closure_cache[ref] = acc
        return closure_cache[ref]

    resolved = {}
    for ref in sorted(by_ref):
        skill = by_ref[ref]
        deps = sorted(
            ({"ref": e["to"], "type": e["type"], "range": e["range"],
              "pinned": by_ref[e["to"]]["version"]}
             for e in skill["edges"]),
            key=lambda d: (d["ref"], d["type"]))
        resolved[ref] = {
            "ref": ref,
            "name": skill["name"],
            "version": skill["version"],
            "source": skill["source"],
            "dependencies": deps,
            "closure": sorted(_closure(ref)),
        }
    return resolved, []


# ── The lockfile (Cargo.lock analogue) ───────────────────────────────────────

def build_lockfile(doc):
    """Build the resolved-graph lockfile → ``(lock, problems)``.

    Deterministic (entries sorted by ref, closures sorted, NO timestamps):
    the same map always yields the identical lockfile, which is what lets
    Wave 6 run regenerate + ``git diff --exit-code`` as a drift gate and
    couple signing/checksums to the artifact."""
    resolved, problems = resolve_graph(doc)
    if problems:
        return None, problems
    lock = {
        "schema": LOCK_SCHEMA_ID,
        "lock_version": LOCK_VERSION,
        "generated_from": {
            "schema": MAP_SCHEMA_ID,
            "map_version": MAP_VERSION,
            "skill_count": len(resolved),
        },
        "resolved": [resolved[ref] for ref in sorted(resolved)],
    }
    return lock, []


def verify_lockfile(doc, lock) -> list:
    """Check a lockfile against a FRESH resolution → problem list.

    Catches every drift class honestly by name: a header edit, a missing or
    stale entry, a pin that no longer matches the map (``lock-pin-drift``),
    a closure that no longer pins the transitive graph
    (``lock-closure-drift``), a dependency-set change, or a renamed/moved
    skill (``lock-entry-drift``)."""
    fresh, problems = build_lockfile(doc)
    if problems:
        return ["map-unresolvable:%s" % p for p in problems]
    if not isinstance(lock, dict):
        return ["lock-not-an-object"]
    out = []
    for key in ("schema", "lock_version", "generated_from"):
        if lock.get(key) != fresh[key]:
            out.append("lock-header-drift:%s" % key)
    entries = lock.get("resolved")
    if not isinstance(entries, list):
        out.append("lock-resolved-missing")
        return out
    fresh_by = {e["ref"]: e for e in fresh["resolved"]}
    lock_by = {}
    for entry in entries:
        if not isinstance(entry, dict) or not isinstance(entry.get("ref"),
                                                         str):
            out.append("lock-entry-malformed")
            continue
        lock_by[entry["ref"]] = entry
    for ref in sorted(fresh_by):
        if ref not in lock_by:
            out.append("lock-missing-entry:%s" % ref)
    for ref in sorted(lock_by):
        if ref not in fresh_by:
            out.append("lock-stale-entry:%s" % ref)
    for ref in sorted(set(fresh_by) & set(lock_by)):
        f, l = fresh_by[ref], lock_by[ref]
        if l.get("version") != f["version"]:
            out.append("lock-pin-drift:%s" % ref)
        if l.get("dependencies") != f["dependencies"]:
            out.append("lock-dependency-drift:%s" % ref)
        if l.get("closure") != f["closure"]:
            out.append("lock-closure-drift:%s" % ref)
        if l.get("name") != f["name"] or l.get("source") != f["source"]:
            out.append("lock-entry-drift:%s" % ref)
    return out


def dumps_lock(lock) -> str:
    """The ONE canonical lockfile serialization (byte-stable for the Wave-6
    regenerate + ``git diff --exit-code`` gate)."""
    return json.dumps(lock, indent=2, ensure_ascii=False) + "\n"


def write_lockfile(doc=None, path=None):
    """Regenerate the lockfile from the map, deterministically, on disk.

    Raises ``ValueError`` (with every problem) on an unresolvable map —
    never writes a partial lock."""
    doc = doc if doc is not None else load_map()
    lock, problems = build_lockfile(doc)
    if problems:
        raise ValueError("map-unresolvable: " + "; ".join(problems))
    Path(path or LOCK_FILE).write_text(dumps_lock(lock), encoding="utf-8")
    return lock


# ── File loaders ─────────────────────────────────────────────────────────────

def load_map(path=None) -> dict:
    """Load the worktree-local map.json v2 instance."""
    return json.loads(Path(path or MAP_FILE).read_text(encoding="utf-8"))


def load_lockfile(path=None) -> dict:
    """Load the worktree-local resolved-graph lockfile."""
    return json.loads(Path(path or LOCK_FILE).read_text(encoding="utf-8"))
