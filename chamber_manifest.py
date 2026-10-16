"""Chamber-owned sidecar pipeline manifest (steward-chamber W4, F2/E9/C2).

OWNER FILE for ``chamber/manifest-schema.json``. The manifest is the rail's
declared truth — step ids, TYPED edges (the artifactKind riding downstream),
the declared deliverable, per-step yield contracts — as a VERSIONED,
JSON-schema'd document (F2): the lint validates against the in-repo schema
file, never against prose braces, and schema evolution is an explicit
versioned change with a migration note.

WHERE IT LIVES: the project's chamber sidecar,
``.anchor/chamber/pipeline-manifest.json`` — chamber-owned data beside the
projections. The engine spine (``roadmap_events`` — sole writer Ecgberht
``engine/roadmap.mjs``; ``.ecgberht/`` receipts; reflection payloads) is
NEVER written here; the receipt schema is never extended (the manifest hash
is keyed to the commission id READ FROM EXISTING receipt fields).

THE COMMISSION-TIME LINT (:func:`commission_time_lint`) — the three routes:

* a VALID manifest → route ``manifest``: commission proceeds; the manifest
  hash is recorded keyed to the commission id at launch;
* NO manifest on a campaign born UNDER the manifest convention (the sidecar
  convention marker is present — stamped at scaffold-confirm from W4 forward)
  → the named HARD refusal ``manifest_required`` — never a render-time guess;
* NO manifest and NO convention marker → the campaign PREDATES the manifest:
  route ``brownfield-w5`` (the W5 derivation dual path). Hard-refuse extends
  to pre-manifest campaigns only AFTER W5's brownfield derivation lands —
  refusing them today would be a refusal they cannot satisfy.

E9 holds at the data layer: every step's stages carry ``reflection`` AND
``delta_verification`` as DISTINCT tokens; a fixture collapsing the two into
one stage is refused by name.

Stdlib only. Atomic writes + locking ride ``chamber_projections`` (one
sidecar-wide durability discipline, not a second implementation).
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import time
from pathlib import Path

import chamber_projections as _cp

ANCHOR_ROOT = Path(__file__).resolve().parent
SCHEMA_PATH = ANCHOR_ROOT / "chamber" / "manifest-schema.json"

SCHEMA_VERSION = 1

#: Sidecar layout, relative to the PROJECT folder (never an absolute path).
CHAMBER_SIDECAR_REL = _cp.CHAMBER_SIDECAR_REL
MANIFEST_REL = os.path.join(CHAMBER_SIDECAR_REL, "pipeline-manifest.json")
CONVENTION_MARKER_REL = os.path.join(CHAMBER_SIDECAR_REL,
                                     "manifest-convention.json")
HASH_STORE_REL = os.path.join(CHAMBER_SIDECAR_REL, "manifest-hashes.json")
HASH_STORE_LOCK_REL = HASH_STORE_REL + ".lock"

#: E9's two distinct verification stages (exact canonical tokens).
STAGE_EXECUTE = "execute"
STAGE_REFLECTION = "reflection"
STAGE_DELTA_VERIFICATION = "delta_verification"
DEFAULT_STEP_STAGES = (STAGE_EXECUTE, STAGE_REFLECTION,
                       STAGE_DELTA_VERIFICATION)

#: Named lint / hash states (the failure-state table's W4 rows).
ERROR_MANIFEST_REQUIRED = "manifest_required"
ERROR_MANIFEST_INVALID = "manifest_invalid"
ERROR_HASH_MISMATCH = "manifest-hash-mismatch"
STATE_HASH_VERIFIED = "manifest-hash-verified"
STATE_HASH_UNRECORDED = "manifest-hash-unrecorded"
ROUTE_MANIFEST = "manifest"
ROUTE_BROWNFIELD_W5 = "brownfield-w5"
ROUTE_REFUSE = "refuse"

HASH_STORE_SCHEMA = "anchor-chamber-manifest-hashes-v1"

#: Typed-edge artifact kinds derived from the upstream step's commissioned
#: skill (the honest default when a scaffold declares nothing richer).
ARTIFACT_KIND_BY_SKILL = {
    "researchprime": "research-report",
    "crucible": "implementation-plan",
    "foreman": "build-artifacts",
    "gandalf": "advisory-report",
    "jumper": "ideation-report",
}
DEFAULT_ARTIFACT_KIND = "handback"

#: Default per-step yield-contract report-link target: a typed POINTER at the
#: step's landed run record (existing data), never an invented file path.
RUN_RECORD_LINK_PREFIX = "run-record:"


# ── Paths ────────────────────────────────────────────────────────────────────

def manifest_path(folder) -> Path:
    return Path(folder) / MANIFEST_REL


def marker_path(folder) -> Path:
    return Path(folder) / CONVENTION_MARKER_REL


def hash_store_path(folder) -> Path:
    return Path(folder) / HASH_STORE_REL


# ── Schema (F2: the in-repo versioned document the lint validates against) ──

def load_schema(path: Path | None = None) -> dict:
    return json.loads((path or SCHEMA_PATH).read_text(encoding="utf-8"))


def _check_node(value, spec: dict, path: str, problems: list) -> None:
    """Interpret the schema file's restricted JSON-Schema dialect:
    type / const / enum / required / properties / items / minItems /
    minLength. Unknown manifest keys are allowed (forward-compatible)."""
    t = spec.get("type")
    if t == "object":
        if not isinstance(value, dict):
            problems.append("%s: expected object, got %s"
                            % (path, type(value).__name__))
            return
        for key in spec.get("required", []):
            if key not in value:
                problems.append("%s.%s: required key missing" % (path, key))
        for key, sub in (spec.get("properties") or {}).items():
            if key in value:
                _check_node(value[key], sub, "%s.%s" % (path, key), problems)
        return
    if t == "array":
        if not isinstance(value, list):
            problems.append("%s: expected array, got %s"
                            % (path, type(value).__name__))
            return
        if len(value) < spec.get("minItems", 0):
            problems.append("%s: at least %d item(s) required"
                            % (path, spec["minItems"]))
        items = spec.get("items")
        if items:
            for i, item in enumerate(value):
                _check_node(item, items, "%s[%d]" % (path, i), problems)
        return
    if t == "string":
        if not isinstance(value, str):
            problems.append("%s: expected string, got %s"
                            % (path, type(value).__name__))
            return
        if len(value.strip()) < spec.get("minLength", 0):
            problems.append("%s: non-empty string required" % path)
        if "enum" in spec and value not in spec["enum"]:
            problems.append("%s: %r not in %s" % (path, value, spec["enum"]))
        return
    if t == "integer":
        if not isinstance(value, int) or isinstance(value, bool):
            problems.append("%s: expected integer, got %s"
                            % (path, type(value).__name__))
            return
        if "const" in spec and value != spec["const"]:
            problems.append("%s: expected %r, got %r"
                            % (path, spec["const"], value))
        return
    if t == "boolean":
        if not isinstance(value, bool):
            problems.append("%s: expected boolean, got %s"
                            % (path, type(value).__name__))
        return


_COLLAPSE_HINT = re.compile(r"reflection")
_DELTA_HINT = re.compile(r"delta|verif")


def _e9_problems(step: dict, path: str) -> list:
    """E9: reflection and delta verification stay DISTINCT scaffold stages.
    A single token standing in for both is the collapse the lint refuses."""
    problems = []
    stages = [str(s).strip().lower() for s in (step.get("stages") or [])
              if isinstance(s, str) and s.strip()]
    for tok in stages:
        if tok in (STAGE_REFLECTION, STAGE_DELTA_VERIFICATION):
            continue
        if _COLLAPSE_HINT.search(tok) and _DELTA_HINT.search(tok):
            problems.append(
                "%s.stages: E9 — collapsed stage token %r; reflection and "
                "delta verification must be DISTINCT scaffold stages"
                % (path, tok))
    if STAGE_REFLECTION not in stages:
        problems.append("%s.stages: E9 — required distinct stage %r missing"
                        % (path, STAGE_REFLECTION))
    if STAGE_DELTA_VERIFICATION not in stages:
        problems.append("%s.stages: E9 — required distinct stage %r missing"
                        % (path, STAGE_DELTA_VERIFICATION))
    return problems


_WINDOWS_DRIVE = re.compile(r"^[A-Za-z]:")


def _relative_path_problems(rel: str, path: str) -> list:
    """The declared deliverable's outputPath is project-relative by contract —
    an absolute path or a traversal is refused at the data layer."""
    problems = []
    if _WINDOWS_DRIVE.match(rel) or rel.startswith(("/", "\\")):
        problems.append("%s: output_path must be project-relative, got %r"
                        % (path, rel))
    if ".." in rel.replace("\\", "/").split("/"):
        problems.append("%s: output_path may not traverse ('..'): %r"
                        % (path, rel))
    return problems


def validate_manifest(manifest, schema: dict | None = None) -> list:
    """Full manifest validation → problem strings (empty == valid).

    Layer 1 is the schema file's dialect; layer 2 is the semantics the dialect
    cannot express: unique step ids, edges referencing real steps, the honest
    declared-deliverable contract, and the E9 distinct-stage law.
    """
    if not isinstance(manifest, dict):
        return ["manifest: expected a JSON object, got %s"
                % type(manifest).__name__]
    schema = schema or load_schema()
    problems: list = []

    sv = manifest.get("schema_version")
    if sv != schema.get("schema_version"):
        problems.append(
            "manifest.schema_version: %r does not match the in-repo schema "
            "version %r (F2: schema evolution is an explicit versioned change "
            "with a migration note in chamber/manifest-schema.json)"
            % (sv, schema.get("schema_version")))

    _check_node(manifest, schema.get("document") or {}, "manifest", problems)

    steps = manifest.get("steps")
    step_ids: list = []
    if isinstance(steps, list):
        for i, step in enumerate(steps):
            if not isinstance(step, dict):
                continue
            sid = step.get("id")
            if isinstance(sid, str) and sid:
                if sid in step_ids:
                    problems.append("manifest.steps[%d].id: duplicate step id "
                                    "%r" % (i, sid))
                step_ids.append(sid)
            problems.extend(_e9_problems(step, "manifest.steps[%d]" % i))

    edges = manifest.get("edges")
    if isinstance(edges, list):
        known = set(step_ids)
        for i, edge in enumerate(edges):
            if not isinstance(edge, dict):
                continue
            frm, to = edge.get("from"), edge.get("to")
            if frm and frm not in known:
                problems.append("manifest.edges[%d].from: unknown step id %r"
                                % (i, frm))
            if to and to not in known:
                problems.append("manifest.edges[%d].to: unknown step id %r"
                                % (i, to))
            if frm and to and frm == to:
                problems.append("manifest.edges[%d]: self-edge %r" % (i, frm))

    deliv = manifest.get("deliverable")
    if isinstance(deliv, dict):
        if deliv.get("declared") is True:
            for key in ("type", "output_path"):
                if not deliv.get(key):
                    problems.append(
                        "manifest.deliverable.%s: required when declared is "
                        "true (an undeclared deliverable is {declared: false} "
                        "— honest absence, never a partial object)" % key)
            if deliv.get("output_path"):
                problems.extend(_relative_path_problems(
                    str(deliv["output_path"]), "manifest.deliverable.output_path"))
        elif deliv.get("declared") is False:
            for key in ("type", "output_path"):
                if deliv.get(key):
                    problems.append(
                        "manifest.deliverable.%s: present although declared "
                        "is false — declare it or drop it" % key)
    return problems


# ── Read / write / convention marker ─────────────────────────────────────────

def load_manifest(folder) -> dict | None:
    """The project's sidecar manifest, or None when absent. Unparseable JSON
    returns a dict with the named problem (callers refuse, never guess)."""
    p = manifest_path(folder)
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (ValueError, OSError) as exc:
        return {"_unparseable": "pipeline-manifest.json unreadable: %s" % exc}


def write_manifest(folder, manifest: dict) -> dict:
    """Validate then atomically write the sidecar manifest. Writing a manifest
    places the campaign UNDER the manifest convention (marker stamped), so a
    later manifest deletion is a hard lint refusal, never a silent downgrade
    to the brownfield path."""
    problems = validate_manifest(manifest)
    if problems:
        return {"ok": False, "error": ERROR_MANIFEST_INVALID,
                "problems": problems}
    _cp.atomic_write_json(manifest_path(folder), manifest)
    mark_manifest_convention(folder)
    return {"ok": True, "manifest_rel": MANIFEST_REL,
            "manifest_hash": compute_manifest_hash(manifest)}


def mark_manifest_convention(folder, who: str = "chamber") -> dict:
    """Stamp the sidecar convention marker: this campaign's scaffold was born
    under the W4 manifest convention, so commissioning WITHOUT a valid
    manifest is a hard error from here on. Idempotent."""
    p = marker_path(folder)
    if p.exists():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            pass
    marker = {"schema_version": SCHEMA_VERSION,
              "convention": "manifest-required",
              "marked_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
              "marked_by": who}
    _cp.atomic_write_json(p, marker)
    return marker


def under_manifest_convention(folder) -> bool:
    return marker_path(folder).exists()


# ── The commission-time lint (the W4 gate on the commission path) ────────────

def commission_time_lint(folder) -> dict:
    """The gate ``commission_session.confirm_and_launch`` runs BEFORE the
    engine confirm. Returns one of the three routes (module docstring)."""
    manifest = load_manifest(folder)

    if manifest is not None:
        if "_unparseable" in manifest:
            return {"ok": False, "error": ERROR_MANIFEST_INVALID,
                    "route": ROUTE_REFUSE,
                    "problems": [manifest["_unparseable"]],
                    "message": "The sidecar pipeline manifest exists but "
                               "cannot be parsed — fix or regenerate it; "
                               "commissioning will not guess."}
        problems = validate_manifest(manifest)
        if problems:
            return {"ok": False, "error": ERROR_MANIFEST_INVALID,
                    "route": ROUTE_REFUSE, "problems": problems,
                    "message": "The sidecar pipeline manifest fails the F2 "
                               "schema lint — commissioning refused (hard "
                               "error, never a render-time guess)."}
        return {"ok": True, "route": ROUTE_MANIFEST, "manifest": manifest,
                "manifest_hash": compute_manifest_hash(manifest)}

    if under_manifest_convention(folder):
        return {"ok": False, "error": ERROR_MANIFEST_REQUIRED,
                "route": ROUTE_REFUSE,
                "message": "This scaffold was created under the manifest "
                           "convention but has no valid sidecar pipeline "
                           "manifest (.anchor/chamber/pipeline-manifest.json)."
                           " Commissioning a NEW scaffold without a valid "
                           "manifest is refused — a hard error, never a "
                           "render-time guess."}

    return {"ok": True, "route": ROUTE_BROWNFIELD_W5, "pre_manifest": True,
            "message": "Campaign predates the sidecar manifest — routed to "
                       "the W5 brownfield derivation dual path (derive or "
                       "drawn-degraded). Hard refusal extends to pre-manifest "
                       "campaigns only after W5 lands."}


# ── Manifest hash, keyed to the commission id from EXISTING receipt fields ──

def canonical_manifest_bytes(manifest: dict) -> bytes:
    return json.dumps(manifest, sort_keys=True,
                      separators=(",", ":")).encode("utf-8")


def compute_manifest_hash(manifest: dict) -> str:
    return hashlib.sha256(canonical_manifest_bytes(manifest)).hexdigest()


def receipt_commission_id(receipt: dict | None):
    """The commission id READ FROM EXISTING receipt fields (the Anchor run
    record / engine confirm job both already carry ``commission_id``, with
    ``job_id`` the historical alias). NEVER writes or extends the receipt —
    the receipt schema is untouched by this whole build (spine non-goal)."""
    r = receipt or {}
    cid = r.get("commission_id") or r.get("job_id")
    field = ("commission_id" if r.get("commission_id")
             else ("job_id" if r.get("job_id") else None))
    return cid, field


def _load_hash_store(folder) -> dict:
    p = hash_store_path(folder)
    if not p.exists():
        return {"schema": HASH_STORE_SCHEMA, "records": {}}
    try:
        doc = json.loads(p.read_text(encoding="utf-8"))
        if not isinstance(doc, dict) or not isinstance(doc.get("records"), dict):
            raise ValueError("hash store is not a {schema, records} doc")
        return doc
    except (ValueError, OSError) as exc:
        raise _cp.ProjectionStoreError(
            _cp.ERROR_STORE_UNREADABLE,
            "manifest hash store unreadable (%s): %s" % (HASH_STORE_REL, exc))


def record_manifest_hash(folder, receipt: dict) -> dict:
    """Record the CURRENT manifest's hash in the chamber sidecar, keyed to the
    commission id read from the receipt's existing fields."""
    cid, field = receipt_commission_id(receipt)
    if not cid:
        return {"ok": False, "error": "receipt-commission-id-missing",
                "message": "the receipt carries neither commission_id nor "
                           "job_id — nothing to key the manifest hash to"}
    manifest = load_manifest(folder)
    if manifest is None or "_unparseable" in manifest:
        return {"ok": False, "error": "manifest-missing",
                "message": "no readable sidecar manifest to hash"}
    h = compute_manifest_hash(manifest)
    with _cp.file_lock(Path(folder) / HASH_STORE_LOCK_REL):
        store = _load_hash_store(folder)
        store["records"][str(cid)] = {
            "manifest_hash": h,
            "recorded_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "receipt_field_read": field,
        }
        _cp.atomic_write_json(hash_store_path(folder), store)
    return {"ok": True, "commission_id": cid, "manifest_hash": h}


def verify_manifest_hash(folder, commission_id) -> dict:
    """Recompute-and-verify: the rail data layer's check that the manifest an
    in-flight commission describes is the manifest that was commissioned.
    A mismatch is the NAMED error state ``manifest-hash-mismatch`` — rendered,
    never silently repaired; the receipt is never touched."""
    store = _load_hash_store(folder)
    rec = store["records"].get(str(commission_id))
    if not rec:
        return {"ok": False, "state": STATE_HASH_UNRECORDED,
                "error": STATE_HASH_UNRECORDED,
                "commission_id": commission_id,
                "message": "no manifest hash recorded for this commission id"}
    manifest = load_manifest(folder)
    if manifest is None or "_unparseable" in manifest:
        return {"ok": False, "state": ERROR_HASH_MISMATCH,
                "error": ERROR_HASH_MISMATCH,
                "commission_id": commission_id,
                "recorded_hash": rec["manifest_hash"], "current_hash": None,
                "message": "the commissioned manifest is gone/unreadable — "
                           "the recorded hash cannot be reproduced"}
    current = compute_manifest_hash(manifest)
    if current != rec["manifest_hash"]:
        return {"ok": False, "state": ERROR_HASH_MISMATCH,
                "error": ERROR_HASH_MISMATCH,
                "commission_id": commission_id,
                "recorded_hash": rec["manifest_hash"],
                "current_hash": current,
                "message": "the sidecar manifest was edited after commission "
                           "— it no longer describes what was commissioned "
                           "(named error state; the rail renders it, nothing "
                           "silently repairs it)"}
    return {"ok": True, "state": STATE_HASH_VERIFIED,
            "commission_id": commission_id, "manifest_hash": current}


# ── Deterministic derivation from a just-confirmed scaffold ──────────────────

def _read_roadmap_steps(folder) -> list:
    """READ-ONLY look at the spine's derived step list (roadmap_projection —
    single writer engine/roadmap.mjs; reading is the chamber's right, writing
    never is). Returns [] when nothing is readable."""
    p = Path(folder) / "roadmap.json"
    if not p.exists():
        return []
    try:
        doc = json.loads(p.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return []
    steps = doc.get("roadmap_projection")
    if not isinstance(steps, list):
        return []
    out = []
    for s in steps:
        if isinstance(s, dict) and s.get("id") and s.get("name"):
            out.append({"id": str(s["id"]), "name": str(s["name"]),
                        "skill": (s.get("commissioned_as") or None)})
    return out


def derive_manifest_for_scaffold(steps: list, proposal_id: str,
                                 deliverable: dict | None = None) -> dict:
    """A deterministic, no-invention manifest for a JUST-CONFIRMED scaffold:
    sequential typed edges (artifact kind from the upstream step's skill),
    default yield contracts pointing at the step's run record, E9-distinct
    stages, and an HONEST deliverable ({declared: false} unless the confirm
    actually declared one — nothing fabricated)."""
    msteps, edges = [], []
    for i, s in enumerate(steps):
        sid = str(s.get("id"))
        msteps.append({
            "id": sid,
            "name": str(s.get("name")),
            "skill": (str(s["skill"]) if s.get("skill") else ""),
            "stages": list(DEFAULT_STEP_STAGES),
            "yield": {
                "shape": "one-line yield for '%s'" % s.get("name"),
                "report_link": RUN_RECORD_LINK_PREFIX + sid,
            },
        })
        if i > 0:
            prev = steps[i - 1]
            kind = ARTIFACT_KIND_BY_SKILL.get(
                str(prev.get("skill") or "").lower(), DEFAULT_ARTIFACT_KIND)
            edges.append({"from": str(prev.get("id")), "to": sid,
                          "artifact_kind": kind})
    if not (isinstance(deliverable, dict) and deliverable.get("declared")
            and deliverable.get("type") and deliverable.get("output_path")):
        deliverable = {"declared": False}
    return {
        "schema_version": SCHEMA_VERSION,
        "scaffold": {"proposal_id": str(proposal_id or "scaffold")},
        "steps": msteps,
        "edges": edges,
        "deliverable": deliverable,
    }


def establish_manifest_convention(folder, *, proposal_id=None,
                                  deliverable=None, who="john") -> dict:
    """The scaffold-confirm hook: derive + write the initial sidecar manifest
    for the just-confirmed scaffold, placing the campaign under the manifest
    convention. FAIL-OPEN: when no scaffold steps are readable, nothing is
    stamped — the campaign stays on the honest brownfield dual path rather
    than being refused a manifest nothing wrote (the marker is only ever
    stamped alongside a valid manifest)."""
    try:
        if not Path(folder).is_dir():
            return {"ok": False, "reason": "no-project-folder"}
        steps = _read_roadmap_steps(folder)
        if not steps:
            return {"ok": False, "reason": "no-scaffold-steps"}
        manifest = derive_manifest_for_scaffold(
            steps, proposal_id or "scaffold", deliverable)
        out = write_manifest(folder, manifest)
        if not out.get("ok"):
            return {"ok": False, "reason": "derived-manifest-invalid",
                    "problems": out.get("problems")}
        mark_manifest_convention(folder, who=who)
        return {"ok": True, "steps": len(steps),
                "manifest_rel": MANIFEST_REL,
                "manifest_hash": out.get("manifest_hash")}
    except Exception as exc:
        return {"ok": False, "reason": "establish-threw",
                "detail": str(exc)[:200]}
