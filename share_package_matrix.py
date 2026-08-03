"""Shareable package matrix — emit only Skills (A) or Anchor+Skills (B).

Wave 1 contract module. Hard-fails Anchor-only artifact names. Package B
requires a declared ``skills_pin`` and a skills subtree. Does not write
release artifacts (publish path is W3); this module is the fail-closed
validator / emit decision used by later publish gates.

Stdlib only. Consumes schemas/data via ``share_contracts``.
"""

from __future__ import annotations

from share_contracts import (
    PACKAGE_IDS,
    PACKAGE_REASON_CODES,
    load_data,
    validate_package_matrix_doc,
)


class PackageMatrixError(Exception):
    """Raised when a publish request is refused (fail closed)."""

    def __init__(self, reason_codes, message=None):
        codes = list(reason_codes) if reason_codes else ["emit_refused"]
        for c in codes:
            if c not in PACKAGE_REASON_CODES:
                # still attach unknown codes but flag them
                pass
        self.reason_codes = codes
        self.message = message or ("package matrix refused: " + ",".join(codes))
        super().__init__(self.message)


def _normalize_name(name: str) -> str:
    return (name or "").strip().lower().replace("_", "-")


def load_matrix(path=None) -> dict:
    if path is None:
        return load_data("package_matrix")
    from share_contracts import load_json
    return load_json(path)


def matrix_problems(doc=None) -> list:
    return validate_package_matrix_doc(doc if doc is not None else load_matrix())


def _package_by_id(doc, package_id):
    for pkg in doc.get("packages") or []:
        if isinstance(pkg, dict) and pkg.get("id") == package_id:
            return pkg
    return None


def _package_by_artifact_name(doc, artifact_name):
    norm = _normalize_name(artifact_name)
    for pkg in doc.get("packages") or []:
        if not isinstance(pkg, dict):
            continue
        for n in pkg.get("artifact_names") or []:
            if _normalize_name(n) == norm:
                return pkg
    return None


def is_anchor_only_name(artifact_name, doc=None) -> bool:
    """True if the artifact name matches a forbidden Anchor-only pattern."""
    doc = doc if doc is not None else load_matrix()
    norm = _normalize_name(artifact_name)
    for pattern in doc.get("forbidden_artifact_patterns") or []:
        if _normalize_name(pattern) == norm:
            return True
    # Also treat "anchor" alone and obvious Anchor-without-skills shapes.
    if norm in ("anchor", "anchor-only", "anchor_only", "anchoronly"):
        return True
    # Names that include anchor but not skills are treated as Anchor-only.
    if "anchor" in norm and "skill" not in norm:
        # allow explicit dual names already registered on package B
        if _package_by_artifact_name(doc, artifact_name) is not None:
            return False
        return True
    return False


def validate_publish_request(request, doc=None) -> list:
    """Validate a publish request → list of reason codes (empty = allowed).

    A publish request is a dict with at least ``artifact_name``. Optional:
    ``package_id``, ``skills_pin`` ({tag, commit}), ``skills_subtree_present``,
    ``version``.
    """
    doc = doc if doc is not None else load_matrix()
    matrix_errs = validate_package_matrix_doc(doc)
    if matrix_errs:
        return ["emit_refused"]

    if not isinstance(request, dict):
        return ["emit_refused"]

    name = request.get("artifact_name")
    if not isinstance(name, str) or not name.strip():
        return ["unknown_artifact_name"]

    if is_anchor_only_name(name, doc):
        return ["anchor_only_forbidden"]

    pkg = None
    pid = request.get("package_id")
    if pid is not None:
        if pid not in PACKAGE_IDS:
            return ["unknown_package_id"]
        pkg = _package_by_id(doc, pid)
        if pkg is None:
            return ["unknown_package_id"]
        # If artifact maps to a different package, mismatch.
        by_name = _package_by_artifact_name(doc, name)
        if by_name is not None and by_name.get("id") != pid:
            return ["package_id_artifact_mismatch"]
        # Named artifact must be known OR explicit package_id provided.
        if by_name is None:
            # allow package_id-driven emit when name is novel but not forbidden
            pass
    else:
        pkg = _package_by_artifact_name(doc, name)
        if pkg is None:
            return ["unknown_artifact_name"]
        pid = pkg.get("id")

    codes = []
    if pkg is None:
        return ["unknown_package_id"]

    # B requires skills_pin
    if pkg.get("requires_skills_pin"):
        pin = request.get("skills_pin")
        if not isinstance(pin, dict):
            codes.append("skills_pin_required")
        else:
            tag = pin.get("tag")
            commit = pin.get("commit")
            if not (isinstance(tag, str) and tag.strip()
                    and isinstance(commit, str) and commit.strip()):
                codes.append("skills_pin_required")

    # Skills subtree required for both A and B when declared
    if pkg.get("requires_skills_subtree"):
        present = request.get("skills_subtree_present")
        # Default: if key omitted, treat as missing only when explicitly False
        # or when caller sets it. For strict fail-closed, missing → required.
        if present is not True:
            codes.append("skills_subtree_required")

    return codes


def assert_emit_allowed(request, doc=None) -> dict:
    """Return an emit decision dict or raise PackageMatrixError (fail closed).

    On success::
        {
          "emit": True,
          "package_id": "A"|"B",
          "artifact_name": str,
          "reason_codes": [],
        }

    On refusal: raises PackageMatrixError with reason_codes; **no package is
    emitted** (callers must not write artifacts after this raises).
    """
    doc = doc if doc is not None else load_matrix()
    codes = validate_publish_request(request, doc=doc)
    if codes:
        raise PackageMatrixError(
            codes,
            message="package matrix refused emit for %r: %s"
            % (request.get("artifact_name"), ",".join(codes)),
        )

    pid = request.get("package_id")
    if pid is None:
        pkg = _package_by_artifact_name(doc, request["artifact_name"])
        pid = pkg["id"] if pkg else None
    return {
        "emit": True,
        "package_id": pid,
        "artifact_name": request.get("artifact_name"),
        "skills_pin": request.get("skills_pin"),
        "reason_codes": [],
    }


def check_freeze_skills_pin(freeze_doc, package_id="B") -> list:
    """Return reason codes if package B freeze lacks a usable skills_pin.

    Used by freeze-manifest / package_matrix coupling checks (W1 GWT #2).
    """
    if package_id != "B":
        return []
    pin = None
    if isinstance(freeze_doc, dict):
        pin = freeze_doc.get("skills_pin")
    if not isinstance(pin, dict):
        return ["skills_pin_required"]
    tag = pin.get("tag")
    commit = pin.get("commit")
    if not (isinstance(tag, str) and tag.strip()
            and isinstance(commit, str) and commit.strip()):
        return ["skills_pin_required"]
    return []


def allowed_package_ids() -> tuple:
    return PACKAGE_IDS
