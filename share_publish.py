"""Publish pipeline gates for Shareable packages A|B (W3).

Fail-closed before any release artifact is written:

* dirty working tree blocks publish
* package matrix: A or B only; Anchor-only names fail
* package B requires skills subtree + skills_pin
* B_contains_A: skills subtree checksum in B equals A for the same pin
* ship_allowed / freeze placeholders block public ship
* full-roster canary (scrub + clean-scan) required before first public-tag
  attempt (still freeze-gated)

Extends GREEN ``share_package_matrix`` / ``vendor_skills`` / ``distro`` — does
not invent a second distro stack. Stdlib only.
"""

from __future__ import annotations

import hashlib
import subprocess
from pathlib import Path

import share_package_matrix as pm
from share_contracts import (
    PLACEHOLDER,
    READINESS_REASON_CODES,
    is_placeholder,
    load_data,
    validate_freeze_manifest_doc,
    validate_sources_pin_doc,
)

# Publish-path reason codes (superset of package-matrix refuse codes).
PUBLISH_REASON_CODES = (
    "dirty_working_tree",
    "anchor_only_forbidden",
    "unknown_package_id",
    "unknown_artifact_name",
    "skills_pin_required",
    "skills_subtree_required",
    "package_id_artifact_mismatch",
    "emit_refused",
    "b_contains_a_mismatch",
    "ship_not_allowed",
    "canary_required",
    "canary_failed",
    "freeze_placeholders_block_ship",
    "skills_pin_mismatch",
)

# Onboard degraded code when local skills diverge from declared B.skills_pin.
# Defined in W1 readiness enum; re-exported here so onboard (W5) has one import.
PIN_MISMATCH_DEGRADED_CODE = "skills_pin_mismatch"

_MODULE_DIR = Path(__file__).resolve().parent


class PublishGateError(Exception):
    """Raised when publish is refused (fail closed; no artifact written)."""

    def __init__(self, reason_codes, message=None):
        codes = list(reason_codes) if reason_codes else ["emit_refused"]
        self.reason_codes = codes
        self.message = message or (
            "publish refused: " + ",".join(codes)
        )
        super().__init__(self.message)


def pin_mismatch_degraded_code() -> str:
    """Reason code for onboard when local skills ≠ declared B.skills_pin."""
    assert PIN_MISMATCH_DEGRADED_CODE in READINESS_REASON_CODES
    return PIN_MISMATCH_DEGRADED_CODE


def check_skills_pin_match(declared_pin, observed_pin) -> list:
    """Return ``[skills_pin_mismatch]`` when tag/commit pairs differ.

    Used by onboard (and publish pin checks) to stamp degraded, not crash.
    Missing/empty observed pin is a mismatch when a declared pin is present.
    """
    if not isinstance(declared_pin, dict):
        return []
    d_tag = (declared_pin.get("tag") or "").strip()
    d_commit = (declared_pin.get("commit") or "").strip()
    if not d_tag and not d_commit:
        return []
    if not isinstance(observed_pin, dict):
        return [PIN_MISMATCH_DEGRADED_CODE]
    o_tag = (observed_pin.get("tag") or "").strip()
    o_commit = (observed_pin.get("commit") or "").strip()
    if d_tag != o_tag or d_commit != o_commit:
        return [PIN_MISMATCH_DEGRADED_CODE]
    return []


# ── Dirty working tree ───────────────────────────────────────────────────────

def _default_git_status_porcelain(repo_root) -> str:
    """Return ``git status --porcelain`` stdout (empty = clean)."""
    root = Path(repo_root)
    try:
        proc = subprocess.run(
            ["git", "-C", str(root), "status", "--porcelain"],
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        # Fail closed: if we cannot prove clean, treat as dirty.
        return "?? (git-status-unavailable)"
    if proc.returncode != 0:
        return "?? (git-status-failed)"
    return proc.stdout or ""


def is_working_tree_dirty(
    repo_root=None,
    *,
    status_text=None,
    git_status_fn=None,
) -> bool:
    """True when the working tree has uncommitted changes.

    Prefer an injected ``status_text`` or ``git_status_fn`` in tests (money-safe,
    no live git required). Live path uses ``git status --porcelain``.
    """
    if status_text is not None:
        return bool(str(status_text).strip())
    root = Path(repo_root) if repo_root is not None else _MODULE_DIR
    fn = git_status_fn or _default_git_status_porcelain
    return bool(str(fn(root) or "").strip())


def check_dirty_tree(
    repo_root=None,
    *,
    status_text=None,
    git_status_fn=None,
) -> list:
    """Return ``[dirty_working_tree]`` if dirty, else ``[]``."""
    if is_working_tree_dirty(
        repo_root, status_text=status_text, git_status_fn=git_status_fn
    ):
        return ["dirty_working_tree"]
    return []


# ── B contains A (skills subtree checksum) ───────────────────────────────────

def skills_subtree_checksum(skills_root) -> str:
    """Deterministic sha256 over relative paths + file bytes under skills_root."""
    root = Path(skills_root)
    h = hashlib.sha256()
    if not root.is_dir():
        h.update(b"<missing-skills-root>")
        return h.hexdigest()
    files = sorted(
        (p for p in root.rglob("*") if p.is_file()),
        key=lambda p: p.relative_to(root).as_posix(),
    )
    for path in files:
        rel = path.relative_to(root).as_posix().encode("utf-8")
        h.update(rel)
        h.update(b"\0")
        try:
            h.update(path.read_bytes())
        except OSError:
            h.update(b"<unreadable>")
        h.update(b"\0")
    return h.hexdigest()


def check_b_contains_a(
    package_a_skills_root,
    package_b_skills_root,
    *,
    skills_pin=None,
) -> list:
    """Skills subtree checksum in B must equal A for the same skills_pin.

    Returns ``[]`` when equal, else ``[b_contains_a_mismatch]``.
    ``skills_pin`` is recorded for callers/logs; equality is content-based.
    """
    del skills_pin  # pin identity is caller's concern; content must match
    a_sum = skills_subtree_checksum(package_a_skills_root)
    b_sum = skills_subtree_checksum(package_b_skills_root)
    if a_sum != b_sum:
        return ["b_contains_a_mismatch"]
    return []


# ── Freeze / ship gate ───────────────────────────────────────────────────────

def check_ship_allowed(
    *,
    sources_doc=None,
    freeze_doc=None,
    public_tag_attempt: bool = False,
) -> list:
    """Block public ship while placeholders remain or ship_allowed is false."""
    if not public_tag_attempt:
        return []
    codes = []
    src = sources_doc
    if src is None:
        try:
            src = load_data("sources_pin")
        except Exception:
            src = None
    frz = freeze_doc
    if frz is None:
        try:
            frz = load_data("freeze_manifest")
        except Exception:
            frz = None

    if isinstance(src, dict):
        if src.get("ship_allowed") is not True:
            codes.append("ship_not_allowed")
        sp = src.get("skills_pin") or {}
        if is_placeholder(sp.get("tag")) or is_placeholder(sp.get("commit")):
            codes.append("freeze_placeholders_block_ship")
        for pin in src.get("pins") or []:
            if isinstance(pin, dict) and (
                is_placeholder(pin.get("tag"))
                or is_placeholder(pin.get("commit"))
            ):
                if "freeze_placeholders_block_ship" not in codes:
                    codes.append("freeze_placeholders_block_ship")
                break
    else:
        codes.append("ship_not_allowed")

    if isinstance(frz, dict):
        if frz.get("ship_allowed") is not True:
            if "ship_not_allowed" not in codes:
                codes.append("ship_not_allowed")
        fsp = frz.get("skills_pin") or {}
        if is_placeholder(fsp.get("tag")) or is_placeholder(fsp.get("commit")):
            if "freeze_placeholders_block_ship" not in codes:
                codes.append("freeze_placeholders_block_ship")
    return codes


def check_full_roster_canary(
    *,
    public_tag_attempt: bool = False,
    canary_ok=None,
    canary_report=None,
) -> list:
    """Full-roster canary required before first public-tag attempt.

    ``canary_ok=True`` means scrub + clean-scan already passed under mock
    fixtures. Still freeze-gated separately via :func:`check_ship_allowed`.
    """
    if not public_tag_attempt:
        return []
    if canary_ok is True:
        return []
    if canary_report is not None:
        if isinstance(canary_report, dict) and canary_report.get("ok") is True:
            return []
        return ["canary_failed"]
    return ["canary_required"]


def run_full_roster_canary(
    dest,
    *,
    sources=None,
    vendor_fn=None,
    clean_scan_fn=None,
) -> dict:
    """Run full-roster archive → scrub → clean-scan (money-safe when mocked).

    Does **not** set ship_allowed. Returns
    ``{ok, vendored, skipped, clean_scan_hits, dest}``.
    """
    dest = Path(dest)
    dest.mkdir(parents=True, exist_ok=True)

    if vendor_fn is None:
        import vendor_skills as vs
        vendor_fn = vs.vendor_all
    if clean_scan_fn is None:
        import distro as distro_mod
        clean_scan_fn = distro_mod.scan_staged_dir

    if sources is not None:
        report = vendor_fn(dest, sources=sources)
    else:
        report = vendor_fn(dest)

    hits = clean_scan_fn(dest) or []
    ok = bool(report.get("vendored")) and not hits
    return {
        "ok": ok,
        "vendored": report.get("vendored") or [],
        "skipped": report.get("skipped") or [],
        "clean_scan_hits": hits,
        "dest": str(dest),
        "freeze_gated": True,
        "ship_allowed": False,
    }


# ── Full publish gate evaluation ─────────────────────────────────────────────

def evaluate_publish_gates(
    request,
    *,
    repo_root=None,
    status_text=None,
    git_status_fn=None,
    package_a_skills_root=None,
    package_b_skills_root=None,
    public_tag_attempt: bool = False,
    canary_ok=None,
    canary_report=None,
    sources_doc=None,
    freeze_doc=None,
    matrix_doc=None,
) -> list:
    """Ordered publish gates → reason codes (empty = allowed to write).

    Order is intentional: dirty tree is checked **first** so a mid skill-run
    dirty tree fails before any package matrix emit decision that might side
    effect. Callers must not write artifacts when this returns non-empty.
    """
    # 1. Dirty tree — hard block before anything else.
    codes = check_dirty_tree(
        repo_root, status_text=status_text, git_status_fn=git_status_fn
    )
    if codes:
        return codes

    # 2. Package matrix (A|B only, Anchor-only refuse, B pin + subtree).
    matrix_codes = pm.validate_publish_request(request, doc=matrix_doc)
    if matrix_codes:
        return list(matrix_codes)

    # 3. Public-tag / freeze / ship_allowed.
    ship_codes = check_ship_allowed(
        sources_doc=sources_doc,
        freeze_doc=freeze_doc,
        public_tag_attempt=public_tag_attempt,
    )
    if ship_codes:
        return ship_codes

    # 4. Full-roster canary before first public tag.
    canary_codes = check_full_roster_canary(
        public_tag_attempt=public_tag_attempt,
        canary_ok=canary_ok,
        canary_report=canary_report,
    )
    if canary_codes:
        return canary_codes

    # 5. B contains A when both package skills trees are provided.
    if package_a_skills_root is not None and package_b_skills_root is not None:
        pin = None
        if isinstance(request, dict):
            pin = request.get("skills_pin")
        bca = check_b_contains_a(
            package_a_skills_root,
            package_b_skills_root,
            skills_pin=pin,
        )
        if bca:
            return bca

    return []


def publish_or_refuse(
    request,
    write_artifact_fn=None,
    **gate_kwargs,
) -> dict:
    """Evaluate gates; call ``write_artifact_fn`` only when all gates pass.

    On refusal raises :class:`PublishGateError` **before** any write. When
    ``write_artifact_fn`` is None and gates pass, returns an emit decision
    without writing (dry-run / CI matrix assert).
    """
    codes = evaluate_publish_gates(request, **gate_kwargs)
    if codes:
        raise PublishGateError(
            codes,
            message="publish refused for %r: %s"
            % (
                request.get("artifact_name")
                if isinstance(request, dict)
                else request,
                ",".join(codes),
            ),
        )

    # Matrix emit decision (also fail-closed on matrix).
    decision = pm.assert_emit_allowed(
        request, doc=gate_kwargs.get("matrix_doc")
    )

    written = None
    if write_artifact_fn is not None:
        written = write_artifact_fn(decision)

    return {
        "emit": True,
        "package_id": decision.get("package_id"),
        "artifact_name": decision.get("artifact_name"),
        "skills_pin": decision.get("skills_pin"),
        "reason_codes": [],
        "written": written,
    }


def ci_dirty_tree_block(repo_root=None, **kwargs) -> dict:
    """CI job body: dirty-tree publish block."""
    codes = check_dirty_tree(repo_root, **kwargs)
    return {
        "job": "dirty_tree_publish_block",
        "ok": not codes,
        "reason_codes": codes,
    }


def ci_matrix_assert(request, matrix_doc=None) -> dict:
    """CI job body: package matrix assert (A|B only; Anchor-only fail)."""
    codes = pm.validate_publish_request(request, doc=matrix_doc)
    return {
        "job": "matrix_assert",
        "ok": not codes,
        "reason_codes": codes,
        "package_id": request.get("package_id")
        if isinstance(request, dict)
        else None,
    }


def ci_b_contains_a(
    package_a_skills_root,
    package_b_skills_root,
    *,
    skills_pin=None,
) -> dict:
    """CI job body: B_contains_A checksum equality for a skills_pin."""
    codes = check_b_contains_a(
        package_a_skills_root,
        package_b_skills_root,
        skills_pin=skills_pin,
    )
    return {
        "job": "B_contains_A",
        "ok": not codes,
        "reason_codes": codes,
        "checksum_a": skills_subtree_checksum(package_a_skills_root),
        "checksum_b": skills_subtree_checksum(package_b_skills_root),
        "skills_pin": skills_pin,
    }


# Placeholder re-export for freeze-gated public tag default pin.
DEFAULT_PLACEHOLDER_PIN = {
    "tag": PLACEHOLDER,
    "commit": PLACEHOLDER,
}


def freeze_docs_valid_placeholders(
    *,
    sources_doc=None,
    freeze_doc=None,
) -> list:
    """Schema-level problems for freeze-placeholder mode (W1 validators)."""
    problems = []
    src = sources_doc if sources_doc is not None else load_data("sources_pin")
    frz = freeze_doc if freeze_doc is not None else load_data("freeze_manifest")
    problems.extend(
        validate_sources_pin_doc(src, require_placeholders=True)
    )
    problems.extend(
        validate_freeze_manifest_doc(frz, require_placeholders=True)
    )
    return problems
