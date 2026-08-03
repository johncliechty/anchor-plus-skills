"""Shareable Anchor + Skills — frozen W1 contracts (schemas + validators).

Wave 1 of share-anchor-skills: lock extension-only reuse of the GREEN
share-distro stack and freeze machine-checkable contracts later waves
import rather than re-invent:

* package_matrix / capability_matrix / readiness / SOURCES pin / freeze-manifest
  JSON Schemas under ``share_schemas/``
* brownfield inventory + NS criterion → module/extension gap map
* SUPERSEDES/REUSE machine markers (see also SUPERSEDES-REUSE.md)
* placeholder-only freeze tags until concurrent skill-run merge + John go-ahead

Stdlib only. Validators return problem lists (empty = valid) following the
``foundry_map.validate_map`` style — no third-party jsonschema dep.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

_MODULE_DIR = Path(__file__).resolve().parent
SCHEMA_DIR = _MODULE_DIR / "share_schemas"

SCHEMA_FILES = {
    "package_matrix": SCHEMA_DIR / "package_matrix.schema.json",
    "capability_matrix": SCHEMA_DIR / "capability_matrix.schema.json",
    "readiness": SCHEMA_DIR / "readiness.schema.json",
    "sources_pin": SCHEMA_DIR / "sources_pin.schema.json",
    "freeze_manifest": SCHEMA_DIR / "freeze_manifest.schema.json",
    "skill_journal": SCHEMA_DIR / "skill_journal.schema.json",
    "skill_friction": SCHEMA_DIR / "skill_friction.schema.json",
    "skills_root": SCHEMA_DIR / "skills_root.schema.json",
}

DATA_FILES = {
    "package_matrix": _MODULE_DIR / "share_package_matrix.json",
    "capability_matrix": _MODULE_DIR / "share_capability_matrix.json",
    "sources_pin": _MODULE_DIR / "share_sources_pin.json",
    "freeze_manifest": _MODULE_DIR / "share_freeze_manifest.json",
    "brownfield_inventory": _MODULE_DIR / "share_brownfield_inventory.json",
}

# Freeze / pin values MUST be this exact token in W1 (real tags post-merge).
PLACEHOLDER = "PLACEHOLDER"
_PLACEHOLDER_RE = re.compile(r"^PLACEHOLDER$")

# Machine-checkable reuse markers for Foreman wave templates.
# A later wave that invents a second distro stack without a gap-proof ticket
# fails the reuse-proof check when these markers are required.
REUSE_MARKERS = {
    "reuse:distro": {
        "path": "distro.py",
        "symbols": ("build_distro", "load_manifest", "select_shippable"),
        "forbid_second_stack": True,
    },
    "reuse:vendor_skills": {
        "path": "vendor_skills.py",
        "symbols": (
            "vendor_all",
            "vendor_canary",
            "SKILL_SOURCES",
            "CANARY_SKILL_SOURCES",
        ),
        "forbid_second_stack": True,
    },
    "reuse:onboard": {
        "path": "onboard.py",
        "symbols": ("install_skills", "scaffold_anchor", "generate_token"),
        "forbid_second_stack": True,
    },
    "reuse:registrar": {
        "path": "anchor/registrar.py",
        "symbols": ("build_registrar_unit",),
        "forbid_second_stack": True,
    },
    "reuse:publish_distro": {
        "path": "distro.py",
        "symbols": ("publish_distro",),
        "forbid_second_stack": True,
    },
    "reuse:clean_scan": {
        "path": "distro.py",
        "symbols": ("PersonalDataError", "build_distro"),
        "forbid_second_stack": True,
    },
    "reuse:default_deny_auth": {
        "path": "paths.py",
        "symbols": ("auth_ok", "expected_token"),
        "forbid_second_stack": False,
    },
    "reuse:doctor": {
        "path": "doctor.py",
        "symbols": ("run_doctor",),
        "forbid_second_stack": False,
    },
}

# Closed enums mirrored from schemas (also re-read from schema at load).
# skills-root/v1 (canonical SKILLS_ROOT registry — share_skills_root W0)
SKILLS_ROOT_SCHEMA = "skills-root/v1"
SKILLS_ROOT_INSTALL_MODES = ("junction", "copy")
SKILLS_ROOT_HOSTS = ("claude", "grok", "gemini", "anchor")

PACKAGE_IDS = ("A", "B")
CAPABILITY_ENUM = (
    "works-without-Anchor",
    "degraded-without-Anchor",
    "Anchor-required",
)
PACKAGE_A_POLICIES = ("exclude", "stub", "include")
# not-ready = zero coding seats / interactive dialogue incomplete (fail closed).
# degraded = seat present but other degradation (fork, pin mismatch, etc.).
READINESS_STATUSES = ("ready", "degraded", "not-ready")
READINESS_REASON_CODES = (
    "governance_missing",
    "no_coding_seat",
    "user_accepted_degraded",
    "skills_pin_mismatch",
    "journal_contract_unproven",
    "skill_tree_forked",
    "os_desktop_skipped",
    "anchor_service_unavailable",
    "seat_probe_failed",
    "openai_sole_family_rejected",
    "prereq_missing",
    "interactive_onboard_required",
)
PACKAGE_REASON_CODES = (
    "anchor_only_forbidden",
    "unknown_package_id",
    "unknown_artifact_name",
    "skills_pin_required",
    "skills_subtree_required",
    "package_id_artifact_mismatch",
    "emit_refused",
)
REPO_IDS = ("anchor", "trio", "skill-foundry")

# SUPERSEDES product decisions (this cut only) — machine markers.
SUPERSEDES = {
    "share-distro-4-skill-roster": "expanded full Trio+Foundry roster (config-only path)",
    "ship-anchor-tailscale-v1": "local-only v1; Tailscale/onboard2 deferred",
    "ship-anchor-tidy-idy-exclusion": "Tidy-Idy in roster (degraded-without-Anchor stub in A)",
    "july-topology-hand-edit-public": "one-way public mirror; bot-only public write (W8)",
}


# ── IO ───────────────────────────────────────────────────────────────────────

def load_json(path) -> dict:
    raw = Path(path).read_text(encoding="utf-8")
    doc = json.loads(raw)
    if not isinstance(doc, dict):
        raise ValueError("json-root-not-object:%s" % path)
    return doc


def load_schema(name: str) -> dict:
    path = SCHEMA_FILES.get(name)
    if path is None:
        raise KeyError("unknown-schema:%s" % name)
    return load_json(path)


def load_data(name: str) -> dict:
    path = DATA_FILES.get(name)
    if path is None:
        raise KeyError("unknown-data:%s" % name)
    return load_json(path)


def is_placeholder(value) -> bool:
    return isinstance(value, str) and bool(_PLACEHOLDER_RE.match(value))


# ── Shared structural helpers ────────────────────────────────────────────────

def _req_keys(doc, required, where=""):
    out = []
    prefix = (where + ":") if where else ""
    for key in required:
        if key not in doc:
            out.append("%smissing-key:%s" % (prefix, key))
    return out


def _unknown_keys(doc, allowed, where=""):
    out = []
    prefix = (where + ":") if where else ""
    for key in doc:
        if key not in allowed:
            out.append("%sunknown-key:%s" % (prefix, key))
    return out


def _const(doc, key, expected, where=""):
    if key not in doc:
        return []
    if doc[key] != expected:
        prefix = (where + ":") if where else ""
        return ["%s%s-wrong:%r" % (prefix, key, doc[key])]
    return []


# ── package_matrix schema validation ────────────────────────────────────────

def validate_package_matrix_doc(doc) -> list:
    """Validate a package_matrix document → problem list (empty = valid)."""
    if not isinstance(doc, dict):
        return ["package-matrix-not-an-object"]
    problems = []
    problems.extend(_req_keys(
        doc, ("schema", "schema_version", "packages", "forbidden_artifact_patterns")
    ))
    problems.extend(_unknown_keys(
        doc, ("schema", "schema_version", "packages", "forbidden_artifact_patterns")
    ))
    problems.extend(_const(doc, "schema", "share-package-matrix/v1"))
    problems.extend(_const(doc, "schema_version", 1))

    packages = doc.get("packages")
    if not isinstance(packages, list) or len(packages) < 2:
        problems.append("packages-missing-or-too-few")
        return problems

    seen_ids = set()
    for idx, pkg in enumerate(packages):
        where = "packages[%d]" % idx
        if not isinstance(pkg, dict):
            problems.append("%s:not-an-object" % where)
            continue
        req = (
            "id", "name", "artifact_names", "includes_anchor", "includes_skills",
            "requires_skills_pin", "requires_skills_subtree",
        )
        problems.extend(_req_keys(pkg, req, where))
        problems.extend(_unknown_keys(
            pkg, req + ("version",), where
        ))
        pid = pkg.get("id")
        if pid not in PACKAGE_IDS:
            problems.append("%s:package-id-out-of-enum:%r" % (where, pid))
        elif pid in seen_ids:
            problems.append("%s:duplicate-package-id:%s" % (where, pid))
        else:
            seen_ids.add(pid)
        if not isinstance(pkg.get("name"), str) or not (pkg.get("name") or "").strip():
            problems.append("%s:name-empty" % where)
        names = pkg.get("artifact_names")
        if not isinstance(names, list) or not names:
            problems.append("%s:artifact_names-missing-or-empty" % where)
        else:
            for n in names:
                if not isinstance(n, str) or not n.strip():
                    problems.append("%s:artifact_name-empty" % where)
        for bkey in ("includes_anchor", "includes_skills",
                     "requires_skills_pin", "requires_skills_subtree"):
            if bkey in pkg and not isinstance(pkg[bkey], bool):
                problems.append("%s:%s-not-bool" % (where, bkey))
        # Coupling invariants from NS: A has no Anchor; B has Anchor+skills+pin
        if pid == "A":
            if pkg.get("includes_anchor") is True:
                problems.append("%s:A-must-not-include-anchor" % where)
            if pkg.get("includes_skills") is False:
                problems.append("%s:A-must-include-skills" % where)
        if pid == "B":
            if pkg.get("includes_anchor") is not True:
                problems.append("%s:B-must-include-anchor" % where)
            if pkg.get("includes_skills") is not True:
                problems.append("%s:B-must-include-skills" % where)
            if pkg.get("requires_skills_pin") is not True:
                problems.append("%s:B-must-require-skills_pin" % where)
            if pkg.get("requires_skills_subtree") is not True:
                problems.append("%s:B-must-require-skills-subtree" % where)

    if "A" not in seen_ids or "B" not in seen_ids:
        problems.append("packages-must-define-A-and-B")

    forb = doc.get("forbidden_artifact_patterns")
    if not isinstance(forb, list) or not forb:
        problems.append("forbidden_artifact_patterns-missing-or-empty")
    else:
        for p in forb:
            if not isinstance(p, str) or not p.strip():
                problems.append("forbidden-pattern-empty")
    return problems


# ── capability_matrix schema validation ─────────────────────────────────────

def validate_capability_matrix_doc(doc) -> list:
    if not isinstance(doc, dict):
        return ["capability-matrix-not-an-object"]
    problems = []
    problems.extend(_req_keys(doc, ("schema", "schema_version", "skills")))
    problems.extend(_unknown_keys(doc, ("schema", "schema_version", "skills")))
    problems.extend(_const(doc, "schema", "share-capability-matrix/v1"))
    problems.extend(_const(doc, "schema_version", 1))
    skills = doc.get("skills")
    if not isinstance(skills, list) or not skills:
        problems.append("skills-missing-or-empty")
        return problems
    seen = set()
    id_re = re.compile(r"^[a-z][a-z0-9-]*$")
    for idx, skill in enumerate(skills):
        where = "skills[%d]" % idx
        if not isinstance(skill, dict):
            problems.append("%s:not-an-object" % where)
            continue
        req = (
            "skill_id", "display_name", "suite", "capability",
            "package_a_policy", "degraded_label",
        )
        problems.extend(_req_keys(skill, req, where))
        problems.extend(_unknown_keys(skill, req, where))
        sid = skill.get("skill_id")
        if not isinstance(sid, str) or not id_re.match(sid or ""):
            problems.append("%s:skill_id-invalid:%r" % (where, sid))
        elif sid in seen:
            problems.append("%s:duplicate-skill_id:%s" % (where, sid))
        else:
            seen.add(sid)
        if skill.get("capability") not in CAPABILITY_ENUM:
            problems.append("%s:capability-out-of-enum:%r" % (
                where, skill.get("capability")))
        if skill.get("package_a_policy") not in PACKAGE_A_POLICIES:
            problems.append("%s:package_a_policy-out-of-enum:%r" % (
                where, skill.get("package_a_policy")))
        if skill.get("suite") not in ("trio", "foundry", "anchor-feature"):
            problems.append("%s:suite-out-of-enum:%r" % (where, skill.get("suite")))
        if not isinstance(skill.get("degraded_label"), str) or not (
                skill.get("degraded_label") or "").strip():
            problems.append("%s:degraded_label-empty" % where)
        # Anchor-required must not be full-include on Skills-only (A)
        if (skill.get("capability") == "Anchor-required"
                and skill.get("package_a_policy") == "include"):
            problems.append(
                "%s:anchor-required-cannot-include-on-A:%s" % (where, sid)
            )
    return problems


# ── skills-root/v1 registry validation (delegates to share_skills_root) ──────

def validate_skills_root_doc(doc) -> list:
    """Validate a skills-root/v1 registry document (problem list; empty = ok)."""
    # Local import keeps share_contracts loadable without pulling vendor_skills
    # for callers that only need matrices; W0 equality/registry tests import
    # share_skills_root directly.
    import share_skills_root as ssr

    return ssr.validate_skills_root_doc(doc)


# ── readiness stamp validation ───────────────────────────────────────────────

def validate_readiness_doc(doc) -> list:
    if not isinstance(doc, dict):
        return ["readiness-not-an-object"]
    problems = []
    problems.extend(_req_keys(
        doc, ("schema", "schema_version", "status", "reason_codes", "package_id")
    ))
    allowed = (
        "schema", "schema_version", "status", "reason_codes", "package_id",
        "governance_installed", "coding_seat_ok", "user_accepted_degraded",
        "feedback_opt_in", "notes",
    )
    problems.extend(_unknown_keys(doc, allowed))
    problems.extend(_const(doc, "schema", "share-readiness/v1"))
    problems.extend(_const(doc, "schema_version", 1))
    if doc.get("status") not in READINESS_STATUSES:
        problems.append("status-out-of-enum:%r" % (doc.get("status"),))
    if doc.get("package_id") not in PACKAGE_IDS:
        problems.append("package_id-out-of-enum:%r" % (doc.get("package_id"),))
    codes = doc.get("reason_codes")
    if not isinstance(codes, list):
        problems.append("reason_codes-not-a-list")
    else:
        for c in codes:
            if c not in READINESS_REASON_CODES:
                problems.append("reason_code-out-of-enum:%r" % (c,))
    # False-green guard (schema-level): ready without governance+seat and
    # without user_accepted_degraded is invalid.
    if doc.get("status") == "ready":
        gov = doc.get("governance_installed")
        seat = doc.get("coding_seat_ok")
        accepted = doc.get("user_accepted_degraded")
        if not ((gov is True and seat is True) or accepted is True):
            problems.append("ready-without-governance-seat-or-accepted-degraded")
    return problems


# ── SOURCES multi-repo pin validation ────────────────────────────────────────

def validate_sources_pin_doc(doc, *, require_placeholders: bool = True) -> list:
    if not isinstance(doc, dict):
        return ["sources-pin-not-an-object"]
    problems = []
    req = (
        "schema", "schema_version", "pins", "package_versions",
        "skills_pin", "scrub_tool_versions", "ship_allowed",
    )
    problems.extend(_req_keys(doc, req))
    problems.extend(_unknown_keys(
        doc, req + ("ship_allowed_stamp_text",)
    ))
    problems.extend(_const(doc, "schema", "share-sources-pin/v1"))
    problems.extend(_const(doc, "schema_version", 1))
    pins = doc.get("pins")
    if not isinstance(pins, list) or not pins:
        problems.append("pins-missing-or-empty")
    else:
        seen_repos = set()
        for idx, pin in enumerate(pins):
            where = "pins[%d]" % idx
            if not isinstance(pin, dict):
                problems.append("%s:not-an-object" % where)
                continue
            problems.extend(_req_keys(pin, ("repo", "tag", "commit"), where))
            if pin.get("repo") not in REPO_IDS:
                problems.append("%s:repo-out-of-enum:%r" % (where, pin.get("repo")))
            else:
                if pin["repo"] in seen_repos:
                    problems.append("%s:duplicate-repo:%s" % (where, pin["repo"]))
                seen_repos.add(pin["repo"])
            if require_placeholders:
                for k in ("tag", "commit"):
                    if k in pin and not is_placeholder(pin[k]):
                        problems.append(
                            "%s:%s-not-placeholder:%r" % (where, k, pin[k])
                        )
    pv = doc.get("package_versions")
    if not isinstance(pv, dict):
        problems.append("package_versions-not-an-object")
    else:
        for pid in PACKAGE_IDS:
            if pid not in pv:
                problems.append("package_versions-missing:%s" % pid)
            elif not isinstance(pv[pid], str) or not pv[pid].strip():
                problems.append("package_versions-empty:%s" % pid)
    sp = doc.get("skills_pin")
    if not isinstance(sp, dict):
        problems.append("skills_pin-not-an-object")
    else:
        problems.extend(_req_keys(sp, ("tag", "commit"), "skills_pin"))
        if require_placeholders:
            for k in ("tag", "commit"):
                if k in sp and not is_placeholder(sp[k]):
                    problems.append("skills_pin:%s-not-placeholder:%r" % (k, sp[k]))
    if "ship_allowed" in doc and not isinstance(doc["ship_allowed"], bool):
        problems.append("ship_allowed-not-bool")
    if require_placeholders and doc.get("ship_allowed") is True:
        problems.append("ship_allowed-true-while-placeholders")
    scrub = doc.get("scrub_tool_versions")
    if scrub is not None and not isinstance(scrub, dict):
        problems.append("scrub_tool_versions-not-an-object")
    return problems


# ── freeze-manifest validation ───────────────────────────────────────────────

def validate_freeze_manifest_doc(doc, *, require_placeholders: bool = True) -> list:
    if not isinstance(doc, dict):
        return ["freeze-manifest-not-an-object"]
    problems = []
    req = (
        "schema", "schema_version", "freeze_tags", "skills_pin",
        "package_matrix_version", "ship_allowed",
    )
    problems.extend(_req_keys(doc, req))
    problems.extend(_unknown_keys(
        doc, req + ("freeze_commits", "notes")
    ))
    problems.extend(_const(doc, "schema", "share-freeze-manifest/v1"))
    problems.extend(_const(doc, "schema_version", 1))
    tags = doc.get("freeze_tags")
    if not isinstance(tags, dict):
        problems.append("freeze_tags-not-an-object")
    else:
        for repo in REPO_IDS:
            if repo not in tags:
                problems.append("freeze_tags-missing:%s" % repo)
            elif require_placeholders and not is_placeholder(tags[repo]):
                problems.append(
                    "freeze_tags:%s-not-placeholder:%r" % (repo, tags[repo])
                )
    commits = doc.get("freeze_commits")
    if commits is not None:
        if not isinstance(commits, dict):
            problems.append("freeze_commits-not-an-object")
        elif require_placeholders:
            for repo, val in commits.items():
                if not is_placeholder(val):
                    problems.append(
                        "freeze_commits:%s-not-placeholder:%r" % (repo, val)
                    )
    sp = doc.get("skills_pin")
    if not isinstance(sp, dict):
        problems.append("skills_pin-not-an-object")
    else:
        problems.extend(_req_keys(sp, ("tag", "commit"), "skills_pin"))
        if require_placeholders:
            for k in ("tag", "commit"):
                if k in sp and not is_placeholder(sp[k]):
                    problems.append("skills_pin:%s-not-placeholder:%r" % (k, sp[k]))
            # B-style freeze check: skills_pin must be present (fields exist);
            # empty / missing already covered. Extra semantic: pin required
            # for any freeze that would ship package B — caller enforces.
    if not isinstance(doc.get("package_matrix_version"), str) or not (
            doc.get("package_matrix_version") or "").strip():
        problems.append("package_matrix_version-empty")
    if "ship_allowed" in doc and not isinstance(doc["ship_allowed"], bool):
        problems.append("ship_allowed-not-bool")
    if require_placeholders and doc.get("ship_allowed") is True:
        problems.append("ship_allowed-true-while-placeholders")
    return problems


# ── brownfield inventory + NS gap map ────────────────────────────────────────

def validate_brownfield_inventory(doc) -> list:
    if not isinstance(doc, dict):
        return ["inventory-not-an-object"]
    problems = []
    problems.extend(_req_keys(
        doc,
        ("schema", "schema_version", "green_modules", "extension_points",
         "ns_gap_map"),
    ))
    problems.extend(_const(doc, "schema", "share-brownfield-inventory/v1"))
    greens = doc.get("green_modules")
    if not isinstance(greens, list) or not greens:
        problems.append("green_modules-missing-or-empty")
    else:
        for g in greens:
            if not isinstance(g, dict):
                problems.append("green_module-not-an-object")
                continue
            for k in ("module", "path", "claims", "reuse_marker", "ns_criteria"):
                if k not in g:
                    problems.append("green_module-missing:%s" % k)
            marker = g.get("reuse_marker")
            if marker and marker not in REUSE_MARKERS:
                problems.append("green_module-unknown-reuse_marker:%s" % marker)
    exts = doc.get("extension_points")
    if not isinstance(exts, list) or not exts:
        problems.append("extension_points-missing-or-empty")
    gap = doc.get("ns_gap_map")
    if not isinstance(gap, dict):
        problems.append("ns_gap_map-not-an-object")
    else:
        for n in range(1, 10):
            key = str(n)
            if key not in gap:
                problems.append("ns_gap_map-missing-criterion:%s" % key)
            else:
                entry = gap[key]
                if not isinstance(entry, dict):
                    problems.append("ns_gap_map-entry-not-object:%s" % key)
                    continue
                green = entry.get("green") or []
                extensions = entry.get("extensions") or []
                if not green and not extensions:
                    problems.append(
                        "ns_gap_map-unmapped-criterion:%s" % key
                    )
    return problems


def every_ns_criterion_mapped(doc=None) -> bool:
    """True iff NS criteria 1–9 each map to ≥1 GREEN module or extension point."""
    doc = doc if doc is not None else load_data("brownfield_inventory")
    problems = validate_brownfield_inventory(doc)
    return not any(p.startswith("ns_gap_map-") for p in problems) and (
        "ns_gap_map-not-an-object" not in problems
        and "ns_gap_map-missing-criterion" not in " ".join(problems)
    )


def check_reuse_marker(marker: str, repo_root=None) -> list:
    """Prove a reuse marker points at a real module path under the repo root.

    Returns a problem list (empty = OK). Does not import symbols (import can
    have side effects); path existence is the W1 machine check.
    """
    if marker not in REUSE_MARKERS:
        return ["unknown-reuse-marker:%s" % marker]
    root = Path(repo_root or _MODULE_DIR)
    info = REUSE_MARKERS[marker]
    path = root / info["path"]
    if not path.is_file():
        return ["reuse-marker-path-missing:%s->%s" % (marker, info["path"])]
    return []


def all_reuse_markers_present(repo_root=None) -> list:
    problems = []
    for marker in sorted(REUSE_MARKERS):
        problems.extend(check_reuse_marker(marker, repo_root=repo_root))
    return problems


# ── bundled validate-all for shipped data files ──────────────────────────────

def validate_shipped_contracts(*, require_placeholders: bool = True) -> dict:
    """Run every W1 validator against the shipped data files.

    Returns ``{name: [problems...]}``; all lists empty ⇒ contracts green.
    """
    return {
        "package_matrix": validate_package_matrix_doc(
            load_data("package_matrix")
        ),
        "capability_matrix": validate_capability_matrix_doc(
            load_data("capability_matrix")
        ),
        "sources_pin": validate_sources_pin_doc(
            load_data("sources_pin"),
            require_placeholders=require_placeholders,
        ),
        "freeze_manifest": validate_freeze_manifest_doc(
            load_data("freeze_manifest"),
            require_placeholders=require_placeholders,
        ),
        "brownfield_inventory": validate_brownfield_inventory(
            load_data("brownfield_inventory")
        ),
        "reuse_markers": all_reuse_markers_present(),
    }
