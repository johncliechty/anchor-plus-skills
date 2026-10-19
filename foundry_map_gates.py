"""Skill Foundry v2 — Wave 6: three drift gates + supply-chain signing.

Wave 5 shipped the machine-readable graph (``foundry_map_v2.json``), its JSON
Schema, and the deterministic resolved-graph lockfile
(``foundry_map_v2.lock.json``). A contract nobody checks drifts; this module
is the checking. Three automated DRIFT GATES, each a pure function returning
``{"gate", "ok", "problems"}`` (honest problem names, never a bare boolean):

1. **schema** (:func:`gate_schema`) — the CI leg: the schema artifact still
   parses, the validator's imported enums still MATCH the schema document
   (anti-drift between the single source and its reader), and the map
   instance validates clean.
2. **lock-regenerate** (:func:`gate_lock_regenerate`) — regenerate the
   lockfile from the map IN MEMORY and require the on-disk artifact to be
   BYTE-IDENTICAL (modulo CRLF) to the fresh serialization — exactly the
   ``regenerate + git diff --exit-code`` semantics, runnable without git.
   :func:`lock_diff_ci_command` is the coupled CI argv for hosts that run
   the git form after :func:`foundry_map.write_lockfile`.
3. **target-existence** (:func:`gate_target_existence`) — the ingest leg:
   every declared edge resolves to a REAL skill — the target ref exists in
   the map AND the target's ``source`` directory exists on disk (relative
   sources resolve against the Skill Foundry root seam).

:func:`run_drift_gates` runs the trio; :func:`ingest_map` is the ONE ingest
entrypoint (load → gate → refuse loudly or return the doc).

**Supply-chain integrity** couples signing/checksums to the LOCKFILE (the
pinned artifact is what a consumer trusts): :func:`sign_lock_text` emits a
deterministic signature document — the lockfile's sha256, a per-resolved-
entry sha256 map, and an HMAC-SHA256 signature over both (key from the
``ANCHOR_FOUNDRY_SIGNING_KEY`` seam; NO baked-in default key — signing
without a key is an honest refusal, never theater).
:func:`verify_lock_signature` fails a tampered lockfile on the KEYLESS
checksum leg alone, and a forged signature document on the keyed HMAC leg
(``hmac.compare_digest``, fail-closed: a signature that cannot be verified
is a problem, never a silent skip).

Consumption lives in ``foundry_skills.build_registry_dispatch`` (the real
consumer reads the map, so a wrong/empty edge breaks a build); this module
is the gate layer both CI and ingest call.

Stdlib only (Anchor's no-dep rule: hashlib/hmac/json/os/pathlib) + the
Wave-1/Wave-5 product seams ``foundry_decisions`` / ``foundry_map``.
"""

import hashlib
import hmac
import json
import os
from pathlib import Path

import foundry_decisions as _fd
import foundry_map as _fm


# ── Constants / seams ────────────────────────────────────────────────────────

#: The canonical Skill Foundry root the map's RELATIVE ``source`` paths
#: resolve against (absolute sources stand alone). Overridable for hermetic
#: tests and non-default installs.
FOUNDRY_ROOT_ENV = "ANCHOR_FOUNDRY_ROOT"
DEFAULT_FOUNDRY_ROOT = r"C:\dev\Skill Foundry"

#: The signature document (worktree-local, next to the lockfile it signs).
SIG_FILE = _fm.LOCK_FILE.with_name("foundry_map_v2.lock.sig.json")
SIG_SCHEMA_ID = "foundry-map-lock-sig/v1"

#: The signing-key seam. There is deliberately NO default key: HMAC with a
#: public constant would be checksum theater, so an absent key refuses to
#: sign and fails verification honestly.
SIGNING_KEY_ENV = "ANCHOR_FOUNDRY_SIGNING_KEY"

#: The gate names (the vocabulary every result/problem row uses).
GATE_SCHEMA = "schema"
GATE_LOCK = "lock-regenerate"
GATE_TARGETS = "target-existence"
GATE_SUPPLY_CHAIN = "supply-chain"
DRIFT_GATES = (GATE_SCHEMA, GATE_LOCK, GATE_TARGETS)

#: Wave-1 anti-drift convention: the artifact traces to a locked North-Star
#: clause (the gates keep the knowledge-graph library honest).
TRACES_TO_NORTH_STAR = (_fd.NS_KNOWLEDGE_GRAPH,)


def _gate(name, problems) -> dict:
    return {"gate": name, "ok": not problems, "problems": list(problems)}


def _norm(text) -> str:
    """Byte-compare canonicalization: CRLF→LF only (a checkout artifact,
    never a semantic difference)."""
    return str(text).replace("\r\n", "\n")


# ── Drift gate 1: schema-in-CI ───────────────────────────────────────────────

def gate_schema(map_doc=None, schema_path=None) -> dict:
    """The CI schema gate: artifact parses, reader agrees, instance valid.

    Red on a broken/malformed schema document, on the validator's imported
    enums drifting from the schema on disk (someone edited the single source
    after import — the reader must be reloaded, not trusted), or on any
    ``foundry_map.validate_map`` problem in the instance."""
    try:
        schema = _fm.load_schema(schema_path)
    except Exception as exc:  # unparseable/missing/malformed — one honest row
        return _gate(GATE_SCHEMA, ["schema-artifact-broken:%s" % exc])
    problems = []
    defs = schema["definitions"]
    for name, imported in (("edge_type", _fm.EDGE_TYPES),
                           ("status", _fm.STATUS_LADDER),
                           ("tier", _fm.TIERS)):
        if tuple(defs.get(name, {}).get("enum") or ()) != imported:
            problems.append("schema-enum-drift:%s" % name)
    if map_doc is None:
        map_doc = _fm.load_map()
    problems.extend(_fm.validate_map(map_doc))
    return _gate(GATE_SCHEMA, problems)


# ── Drift gate 2: regenerate + diff --exit-code ──────────────────────────────

def gate_lock_regenerate(map_doc=None, lock_path=None) -> dict:
    """Regenerate the lockfile from the map; the on-disk artifact must be
    BYTE-IDENTICAL to the fresh canonical serialization.

    Exactly ``git diff --exit-code`` semantics without spawning git: ANY
    byte drift is red (``lock-regen-diff``), even whitespace-only. When the
    stale artifact still parses, the semantic drift rows from
    ``foundry_map.verify_lockfile`` are appended so the failure names WHAT
    drifted, not just that something did."""
    if map_doc is None:
        map_doc = _fm.load_map()
    lock_file = Path(lock_path or _fm.LOCK_FILE)
    fresh, problems = _fm.build_lockfile(map_doc)
    if problems:
        return _gate(GATE_LOCK,
                     ["map-unresolvable:%s" % p for p in problems])
    try:
        on_disk = lock_file.read_text(encoding="utf-8")
    except OSError:
        return _gate(GATE_LOCK, ["lockfile-missing:%s" % lock_file.name])
    if _norm(on_disk) == _fm.dumps_lock(fresh):
        return _gate(GATE_LOCK, [])
    out = ["lock-regen-diff:%s" % lock_file.name]
    try:
        stale = json.loads(on_disk)
    except ValueError:
        out.append("lockfile-unparseable:%s" % lock_file.name)
    else:
        out.extend(_fm.verify_lockfile(map_doc, stale))
    return _gate(GATE_LOCK, out)


def lock_diff_ci_command(lock_path=None) -> list:
    """The coupled CI argv: after ``foundry_map.write_lockfile()`` regenerates
    in place, this is the exact-diff check CI runs (a non-zero exit fails the
    pipeline — the git form of :func:`gate_lock_regenerate`)."""
    name = Path(lock_path or _fm.LOCK_FILE).name
    return ["git", "diff", "--exit-code", "--", name]


# ── Drift gate 3: target-existence at ingest ─────────────────────────────────

def _foundry_root(root=None) -> Path:
    raw = str(root) if root else (
        (os.environ.get(FOUNDRY_ROOT_ENV) or "").strip()
        or DEFAULT_FOUNDRY_ROOT)
    return Path(raw)


def _source_dir(source, root) -> Path:
    p = Path(str(source))
    return p if p.is_absolute() else root / p


def gate_target_existence(map_doc=None, root=None) -> dict:
    """Every declared edge resolves to a REAL skill on disk.

    For each edge: the target ref must exist in the map
    (``edge-target-unknown`` — this gate must stand alone at ingest, not
    presume gate 1 ran) and the TARGET skill's ``source`` directory must
    exist (``edge-target-not-on-disk``). Deliberately edge-scoped per the
    plan: a skill nothing depends on may be absent without failing ingest."""
    if map_doc is None:
        map_doc = _fm.load_map()
    base = _foundry_root(root)
    problems = []
    skills = map_doc.get("skills") if isinstance(map_doc, dict) else None
    if not isinstance(skills, list):
        return _gate(GATE_TARGETS, ["map-not-an-object"])
    by_ref = {s["ref"]: s for s in skills
              if isinstance(s, dict) and isinstance(s.get("ref"), str)}
    checked = set()
    for skill in skills:
        if not isinstance(skill, dict):
            continue
        src = skill.get("ref") if isinstance(skill.get("ref"), str) else "?"
        edges = skill.get("edges")
        for edge in (edges if isinstance(edges, list) else ()):
            if not isinstance(edge, dict):
                continue
            to = edge.get("to")
            if not isinstance(to, str) or not to:
                continue  # structurally broken edge — gate 1's problem
            target = by_ref.get(to)
            if target is None:
                problems.append("edge-target-unknown:%s->%s" % (src, to))
                continue
            if to in checked:
                continue
            checked.add(to)
            d = _source_dir(target.get("source") or "", base)
            if not d.is_dir():
                problems.append("edge-target-not-on-disk:%s->%s:%s"
                                % (src, to, target.get("source")))
    return _gate(GATE_TARGETS, problems)


# ── The trio + the ingest entrypoint ─────────────────────────────────────────

def run_drift_gates(map_doc=None, lock_path=None, root=None,
                    schema_path=None) -> dict:
    """Run all three drift gates → ``{"ok": all-green, "gates": [...]}``."""
    if map_doc is None:
        map_doc = _fm.load_map()
    gates = [
        gate_schema(map_doc, schema_path=schema_path),
        gate_lock_regenerate(map_doc, lock_path=lock_path),
        gate_target_existence(map_doc, root=root),
    ]
    return {"ok": all(g["ok"] for g in gates), "gates": gates}


def ingest_map(map_path=None, lock_path=None, root=None, schema_path=None,
               sig=None, key=None, require_signature=False) -> dict:
    """Load the map THROUGH the gates — the one sanctioned ingest path.

    Runs the three drift gates always, and the supply-chain checksum gate
    when a signature document is supplied (or ``require_signature`` forces
    it — an absent signature is then itself a red row). ANY red gate refuses
    the ingest loudly (``ValueError`` naming every problem); a green run
    returns the loaded map document."""
    doc = _fm.load_map(map_path)
    result = run_drift_gates(doc, lock_path=lock_path, root=root,
                             schema_path=schema_path)
    gates = list(result["gates"])
    if sig is not None or require_signature:
        try:
            lock_text = Path(lock_path or _fm.LOCK_FILE).read_text(
                encoding="utf-8")
        except OSError:
            lock_text = ""
        gates.append(gate_supply_chain(lock_text, sig=sig, key=key))
    bad = ["%s:%s" % (g["gate"], p) for g in gates for p in g["problems"]]
    if bad:
        raise ValueError("map-ingest-refused: " + "; ".join(bad))
    return doc


# ── Supply-chain: signing/checksums coupled to the lockfile ──────────────────

def checksum_text(text) -> str:
    """sha256 hex of the canonical (LF) UTF-8 bytes."""
    return hashlib.sha256(_norm(text).encode("utf-8")).hexdigest()


def _entry_digests(lock) -> dict:
    """Per-resolved-entry sha256 over a canonical (sorted-key) serialization
    — couples the signature to every individual pin, not just the file."""
    out = {}
    for entry in lock.get("resolved") or ():
        if isinstance(entry, dict) and isinstance(entry.get("ref"), str):
            blob = json.dumps(entry, sort_keys=True, ensure_ascii=False,
                              separators=(",", ":"))
            out[entry["ref"]] = hashlib.sha256(
                blob.encode("utf-8")).hexdigest()
    return out


def _signing_payload(lock_sha256, entry_sha256) -> bytes:
    return json.dumps({"lock_sha256": lock_sha256,
                       "entry_sha256": entry_sha256},
                      sort_keys=True, separators=(",", ":")).encode("utf-8")


def _resolve_key(key):
    raw = key if key is not None else (
        os.environ.get(SIGNING_KEY_ENV) or "").strip()
    if not raw:
        return None
    return raw.encode("utf-8") if isinstance(raw, str) else bytes(raw)


def sign_lock_text(lock_text=None, key=None) -> dict:
    """Sign a lockfile serialization → the deterministic signature document.

    No timestamps, no randomness: the same lock bytes + key always yield the
    identical document (regenerable in CI, diffable in git). Refuses honestly
    (``ValueError``) without a key or on an unparseable lockfile — never a
    fabricated signature."""
    if lock_text is None:
        lock_text = _fm.LOCK_FILE.read_text(encoding="utf-8")
    resolved_key = _resolve_key(key)
    if not resolved_key:
        raise ValueError("no-signing-key: pass key= or set %s"
                         % SIGNING_KEY_ENV)
    try:
        lock = json.loads(_norm(lock_text))
    except ValueError as exc:
        raise ValueError("lockfile-unparseable:%s" % exc)
    lock_sha = checksum_text(lock_text)
    entries = _entry_digests(lock)
    signature = hmac.new(resolved_key, _signing_payload(lock_sha, entries),
                         hashlib.sha256).hexdigest()
    return {
        "schema": SIG_SCHEMA_ID,
        "algo": {"checksum": "sha256", "signature": "hmac-sha256"},
        "lock_sha256": lock_sha,
        "entry_sha256": entries,
        "signature": signature,
    }


def write_signature(lock_text=None, key=None, path=None) -> dict:
    """Sign and persist the signature document next to the lockfile."""
    sig = sign_lock_text(lock_text, key=key)
    Path(path or SIG_FILE).write_text(
        json.dumps(sig, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8")
    return sig


def load_signature(path=None) -> dict:
    return json.loads(Path(path or SIG_FILE).read_text(encoding="utf-8"))


def verify_lock_signature(lock_text, sig, key=None) -> list:
    """Verify a lockfile against its signature document → problem list.

    Two independent legs, both fail-closed:

    * **checksum (keyless)** — the whole-file sha256 and every per-entry
      sha256 must match a fresh computation; a tampered lockfile fails HERE,
      no key required (``checksum-mismatch:*``, ``checksum-missing-entry``,
      ``checksum-stale-entry``).
    * **signature (keyed)** — the HMAC over the document's own claimed
      digests must verify (``signature-invalid`` — an attacker who re-hashed
      a tampered lock still cannot forge this without the key). No key
      available → ``signature-unverifiable:no-key`` (a problem, never a
      silent pass)."""
    if not isinstance(sig, dict):
        return ["sig-not-an-object"]
    out = []
    if sig.get("schema") != SIG_SCHEMA_ID:
        out.append("sig-schema-wrong:%r" % (sig.get("schema"),))
    claimed_sha = sig.get("lock_sha256")
    if claimed_sha != checksum_text(lock_text):
        out.append("checksum-mismatch:lockfile")
    claimed_entries = sig.get("entry_sha256")
    if not isinstance(claimed_entries, dict):
        out.append("sig-entry-checksums-missing")
        claimed_entries = {}
    try:
        lock = json.loads(_norm(lock_text))
    except ValueError:
        out.append("lockfile-unparseable")
        lock = {}
    fresh_entries = _entry_digests(lock)
    for ref in sorted(fresh_entries):
        if ref not in claimed_entries:
            out.append("checksum-missing-entry:%s" % ref)
        elif claimed_entries[ref] != fresh_entries[ref]:
            out.append("checksum-mismatch:%s" % ref)
    for ref in sorted(claimed_entries):
        if ref not in fresh_entries:
            out.append("checksum-stale-entry:%s" % ref)
    resolved_key = _resolve_key(key)
    if not resolved_key:
        out.append("signature-unverifiable:no-key")
    else:
        expected = hmac.new(
            resolved_key,
            _signing_payload(claimed_sha, claimed_entries
                             if isinstance(claimed_entries, dict) else {}),
            hashlib.sha256).hexdigest()
        if not hmac.compare_digest(str(sig.get("signature") or ""), expected):
            out.append("signature-invalid")
    return out


def gate_supply_chain(lock_text=None, sig=None, key=None) -> dict:
    """The checksum/signing gate as a gate-result row (defaults read the
    worktree-local lockfile + signature artifacts)."""
    if lock_text is None:
        try:
            lock_text = _fm.LOCK_FILE.read_text(encoding="utf-8")
        except OSError:
            return _gate(GATE_SUPPLY_CHAIN,
                         ["lockfile-missing:%s" % _fm.LOCK_FILE.name])
    if sig is None:
        try:
            sig = load_signature()
        except (OSError, ValueError):
            return _gate(GATE_SUPPLY_CHAIN,
                         ["signature-missing:%s" % SIG_FILE.name])
    return _gate(GATE_SUPPLY_CHAIN,
                 verify_lock_signature(lock_text, sig, key=key))
