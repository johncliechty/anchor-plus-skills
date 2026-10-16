"""Per-skill capability matrix — Trio + Foundry roster Anchor coupling.

Wave 1: works-without-Anchor | degraded-without-Anchor | Anchor-required,
with package A policies (include | stub | exclude) and plain-English
degraded labels. Skills-only roster resolution never crashes on
Anchor-required surfaces — they are excluded or stub-labeled.

Stdlib only.
"""

from __future__ import annotations

from share_contracts import (
    CAPABILITY_ENUM,
    PACKAGE_A_POLICIES,
    load_data,
    validate_capability_matrix_doc,
)


def load_matrix(path=None) -> dict:
    if path is None:
        return load_data("capability_matrix")
    from share_contracts import load_json
    return load_json(path)


def matrix_problems(doc=None) -> list:
    return validate_capability_matrix_doc(
        doc if doc is not None else load_matrix()
    )


def capability_enum() -> tuple:
    return CAPABILITY_ENUM


def package_a_policies() -> tuple:
    return PACKAGE_A_POLICIES


def skills_by_id(doc=None) -> dict:
    doc = doc if doc is not None else load_matrix()
    out = {}
    for skill in doc.get("skills") or []:
        if isinstance(skill, dict) and skill.get("skill_id"):
            out[skill["skill_id"]] = skill
    return out


def get_skill(skill_id: str, doc=None):
    return skills_by_id(doc).get(skill_id)


def resolve_skills_only_roster(doc=None) -> dict:
    """Resolve the Skills-only (package A) roster.

    Returns::
        {
          "included": [skill dicts with package_a_policy include],
          "stubbed":  [skill dicts with policy stub + degraded_label],
          "excluded": [skill dicts with policy exclude + degraded_label],
          "surface":  [entries safe to expose without Anchor — include+stub],
        }

    Anchor-required skills never appear in ``included`` as full surfaces
    without a degraded path: exclude omits them from ``surface``; stub keeps
    them as labeled stubs. Callers must not crash on missing Anchor — use
    ``surface`` / labels only.
    """
    doc = doc if doc is not None else load_matrix()
    problems = validate_capability_matrix_doc(doc)
    if problems:
        # Fail closed to empty surface rather than crash or invent roster.
        return {
            "included": [],
            "stubbed": [],
            "excluded": [],
            "surface": [],
            "validation_problems": problems,
        }

    included, stubbed, excluded = [], [], []
    for skill in doc["skills"]:
        policy = skill.get("package_a_policy")
        entry = dict(skill)
        if policy == "include":
            included.append(entry)
        elif policy == "stub":
            stubbed.append(entry)
        else:
            # exclude (or unknown treated as exclude)
            excluded.append(entry)

    # surface = what Skills-only may present without requiring Anchor
    surface = []
    for entry in included:
        surface.append({
            "skill_id": entry["skill_id"],
            "display_name": entry["display_name"],
            "capability": entry["capability"],
            "status": "included",
            "degraded_label": entry.get("degraded_label") or "",
        })
    for entry in stubbed:
        surface.append({
            "skill_id": entry["skill_id"],
            "display_name": entry["display_name"],
            "capability": entry["capability"],
            "status": "degraded-stub",
            "degraded_label": entry.get("degraded_label") or "",
        })
    # excluded Anchor-required surfaces get explicit labels for docs/UI
    # but are NOT on the runnable surface
    return {
        "included": included,
        "stubbed": stubbed,
        "excluded": excluded,
        "surface": surface,
        "validation_problems": [],
    }


def resolve_package_b_roster(doc=None) -> list:
    """Full suite for Anchor+Skills (package B) — every matrix skill."""
    doc = doc if doc is not None else load_matrix()
    problems = validate_capability_matrix_doc(doc)
    if problems:
        return []
    return [dict(s) for s in doc["skills"]]


def anchor_required_skills(doc=None) -> list:
    doc = doc if doc is not None else load_matrix()
    return [
        s for s in (doc.get("skills") or [])
        if isinstance(s, dict) and s.get("capability") == "Anchor-required"
    ]


def skills_only_safe(skill_id: str, doc=None) -> bool:
    """True if skill may appear on Skills-only runnable surface (include/stub)."""
    skill = get_skill(skill_id, doc)
    if not skill:
        return False
    return skill.get("package_a_policy") in ("include", "stub")


def enum_coverage(doc=None) -> dict:
    """Report which capability enum values appear in the matrix data."""
    doc = doc if doc is not None else load_matrix()
    present = set()
    for s in doc.get("skills") or []:
        if isinstance(s, dict) and s.get("capability"):
            present.add(s["capability"])
    return {
        "required_enum": list(CAPABILITY_ENUM),
        "present": sorted(present),
        "missing": [c for c in CAPABILITY_ENUM if c not in present],
        "complete": all(c in present for c in CAPABILITY_ENUM),
    }
