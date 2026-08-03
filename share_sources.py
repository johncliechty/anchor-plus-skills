"""SOURCES.md multi-repo provenance writer (Shareable Anchor+Skills W3).

Stamps freeze tags/commits, package matrix versions, scrub tool versions,
and ship-allowed stamp text. ``ship_allowed`` stays false until concurrent
skill-run merge + John go-ahead are recorded AND freeze placeholders are
replaced (plan-complete ≠ ship-allowed).

Stdlib only. Consumes W1 schemas/data via ``share_contracts``.
"""

from __future__ import annotations

from pathlib import Path

from share_contracts import (
    PACKAGE_IDS,
    PLACEHOLDER,
    REPO_IDS,
    is_placeholder,
    load_data,
    validate_sources_pin_doc,
)

# Canonical stamp text (NS / Master Plan P1).
SHIP_ALLOWED_STAMP_TEXT = (
    "only after concurrent skill-run merge + John go-ahead"
)

_MODULE_DIR = Path(__file__).resolve().parent


def load_sources_pin(path=None) -> dict:
    if path is None:
        return load_data("sources_pin")
    from share_contracts import load_json
    return load_json(path)


def pin_problems(doc=None, *, require_placeholders: bool = True) -> list:
    return validate_sources_pin_doc(
        doc if doc is not None else load_sources_pin(),
        require_placeholders=require_placeholders,
    )


def go_ahead_conditions_met(
    *,
    concurrent_skill_run_merged: bool = False,
    john_go_ahead: bool = False,
) -> bool:
    """True only when both human/process go-ahead conditions are recorded."""
    return bool(concurrent_skill_run_merged) and bool(john_go_ahead)


def freeze_still_placeholder(doc=None) -> bool:
    """True if any multi-repo pin / skills_pin field is still PLACEHOLDER."""
    doc = doc if doc is not None else load_sources_pin()
    if not isinstance(doc, dict):
        return True
    for pin in doc.get("pins") or []:
        if not isinstance(pin, dict):
            return True
        if is_placeholder(pin.get("tag")) or is_placeholder(pin.get("commit")):
            return True
    sp = doc.get("skills_pin") or {}
    if is_placeholder(sp.get("tag")) or is_placeholder(sp.get("commit")):
        return True
    return False


def may_set_ship_allowed(
    doc=None,
    *,
    concurrent_skill_run_merged: bool = False,
    john_go_ahead: bool = False,
) -> bool:
    """True only when go-ahead is recorded and no freeze placeholders remain."""
    if freeze_still_placeholder(doc):
        return False
    return go_ahead_conditions_met(
        concurrent_skill_run_merged=concurrent_skill_run_merged,
        john_go_ahead=john_go_ahead,
    )


def build_attestation(
    pin_doc=None,
    *,
    vendored_skills=None,
    package_matrix_doc=None,
    concurrent_skill_run_merged: bool = False,
    john_go_ahead: bool = False,
) -> dict:
    """Build a machine attestation dict for SOURCES.md / pin JSON.

    Never silently sets ``ship_allowed`` true while placeholders remain.
    """
    pin_doc = pin_doc if pin_doc is not None else load_sources_pin()
    if not isinstance(pin_doc, dict):
        pin_doc = {}

    pins = []
    for pin in pin_doc.get("pins") or []:
        if isinstance(pin, dict):
            pins.append({
                "repo": pin.get("repo"),
                "tag": pin.get("tag") or PLACEHOLDER,
                "commit": pin.get("commit") or PLACEHOLDER,
            })
    # Ensure all REPO_IDS present (fill missing with placeholders).
    seen = {p["repo"] for p in pins}
    for repo in REPO_IDS:
        if repo not in seen:
            pins.append({
                "repo": repo,
                "tag": PLACEHOLDER,
                "commit": PLACEHOLDER,
            })

    package_versions = {}
    pv = pin_doc.get("package_versions") or {}
    if package_matrix_doc and isinstance(package_matrix_doc, dict):
        for pkg in package_matrix_doc.get("packages") or []:
            if isinstance(pkg, dict) and pkg.get("id") in PACKAGE_IDS:
                package_versions[pkg["id"]] = (
                    pkg.get("version")
                    or pv.get(pkg["id"])
                    or "0.0.0-placeholder"
                )
    for pid in PACKAGE_IDS:
        if pid not in package_versions:
            package_versions[pid] = pv.get(pid) or "0.0.0-placeholder"

    skills_pin = pin_doc.get("skills_pin") if isinstance(
        pin_doc.get("skills_pin"), dict
    ) else {}
    skills_pin = {
        "tag": skills_pin.get("tag") or PLACEHOLDER,
        "commit": skills_pin.get("commit") or PLACEHOLDER,
    }

    scrub = pin_doc.get("scrub_tool_versions")
    if not isinstance(scrub, dict) or not scrub:
        scrub = {
            "distro.py": "GREEN-share-distro",
            "vendor_skills.py": "GREEN-share-distro",
        }

    stamp = (
        pin_doc.get("ship_allowed_stamp_text")
        or SHIP_ALLOWED_STAMP_TEXT
    )

    ship_ok = may_set_ship_allowed(
        {
            "pins": pins,
            "skills_pin": skills_pin,
        },
        concurrent_skill_run_merged=concurrent_skill_run_merged,
        john_go_ahead=john_go_ahead,
    )
    # Never inherit a true ship_allowed from a placeholder pin file.
    if pin_doc.get("ship_allowed") is True and not ship_ok:
        ship_ok = False

    attestation = {
        "schema": "share-sources-pin/v1",
        "schema_version": 1,
        "pins": pins,
        "package_versions": package_versions,
        "skills_pin": skills_pin,
        "scrub_tool_versions": dict(scrub),
        "ship_allowed": bool(ship_ok),
        "ship_allowed_stamp_text": stamp,
        "go_ahead": {
            "concurrent_skill_run_merged": bool(concurrent_skill_run_merged),
            "john_go_ahead": bool(john_go_ahead),
        },
    }
    if vendored_skills:
        attestation["vendored_skills"] = list(vendored_skills)
    return attestation


def render_sources_md(attestation: dict) -> str:
    """Render human-readable SOURCES.md from an attestation dict."""
    lines = [
        "# SOURCES — multi-repo freeze provenance",
        "",
        "Attestation for Shareable Anchor + Skills packages (A = Skills-only,",
        "B = Anchor+Skills). Plan-complete is **not** ship-allowed.",
        "",
        "## Ship gate",
        "",
        "- **ship_allowed:** `%s`" % (
            "true" if attestation.get("ship_allowed") else "false"
        ),
        "- **stamp:** %s" % (
            attestation.get("ship_allowed_stamp_text")
            or SHIP_ALLOWED_STAMP_TEXT
        ),
    ]
    ga = attestation.get("go_ahead") or {}
    lines.append(
        "- **concurrent_skill_run_merged:** `%s`"
        % ("true" if ga.get("concurrent_skill_run_merged") else "false")
    )
    lines.append(
        "- **john_go_ahead:** `%s`"
        % ("true" if ga.get("john_go_ahead") else "false")
    )
    lines.extend([
        "",
        "## Multi-repo pins",
        "",
        "| Repo | Tag | Commit |",
        "|------|-----|--------|",
    ])
    for pin in attestation.get("pins") or []:
        lines.append(
            "| %s | `%s` | `%s` |"
            % (pin.get("repo"), pin.get("tag"), pin.get("commit"))
        )

    lines.extend(["", "## Package matrix versions", ""])
    pv = attestation.get("package_versions") or {}
    for pid in PACKAGE_IDS:
        lines.append("- **Package %s:** `%s`" % (pid, pv.get(pid, "")))

    sp = attestation.get("skills_pin") or {}
    lines.extend([
        "",
        "## Skills pin (package B)",
        "",
        "- **tag:** `%s`" % sp.get("tag", PLACEHOLDER),
        "- **commit:** `%s`" % sp.get("commit", PLACEHOLDER),
        "",
        "## Scrub tool versions",
        "",
    ])
    scrub = attestation.get("scrub_tool_versions") or {}
    for tool, ver in sorted(scrub.items()):
        lines.append("- **%s:** `%s`" % (tool, ver))

    vendored = attestation.get("vendored_skills") or []
    if vendored:
        lines.extend([
            "",
            "## Vendored skills",
            "",
            "| Skill | Archived commit |",
            "|-------|-----------------|",
        ])
        for v in vendored:
            if isinstance(v, dict):
                lines.append(
                    "| %s | `%s` |"
                    % (v.get("name", ""), v.get("commit", ""))
                )
            else:
                lines.append("| %s | |" % v)

    lines.append("")
    return "\n".join(lines)


def write_sources_md(
    dest,
    pin_doc=None,
    *,
    vendored_skills=None,
    package_matrix_doc=None,
    concurrent_skill_run_merged: bool = False,
    john_go_ahead: bool = False,
    filename: str = "SOURCES.md",
) -> dict:
    """Write SOURCES.md under ``dest`` and return the attestation used.

    ``dest`` may be a directory (writes ``dest/SOURCES.md``) or a full file path.
    """
    dest = Path(dest)
    if dest.suffix.lower() == ".md":
        path = dest
        path.parent.mkdir(parents=True, exist_ok=True)
    else:
        dest.mkdir(parents=True, exist_ok=True)
        path = dest / filename

    attestation = build_attestation(
        pin_doc,
        vendored_skills=vendored_skills,
        package_matrix_doc=package_matrix_doc,
        concurrent_skill_run_merged=concurrent_skill_run_merged,
        john_go_ahead=john_go_ahead,
    )
    path.write_text(render_sources_md(attestation), encoding="utf-8")
    attestation["path"] = str(path)
    return attestation


def attestation_as_pin_doc(attestation: dict) -> dict:
    """Project attestation fields into the W1 sources_pin schema shape."""
    return {
        "schema": "share-sources-pin/v1",
        "schema_version": 1,
        "pins": list(attestation.get("pins") or []),
        "package_versions": dict(attestation.get("package_versions") or {}),
        "skills_pin": dict(attestation.get("skills_pin") or {}),
        "scrub_tool_versions": dict(
            attestation.get("scrub_tool_versions") or {}
        ),
        "ship_allowed": bool(attestation.get("ship_allowed")),
        "ship_allowed_stamp_text": attestation.get(
            "ship_allowed_stamp_text"
        ) or SHIP_ALLOWED_STAMP_TEXT,
    }


if __name__ == "__main__":  # pragma: no cover
    import json
    import sys

    out = sys.argv[1] if len(sys.argv) > 1 else "."
    result = write_sources_md(out)
    print(json.dumps({
        "path": result.get("path"),
        "ship_allowed": result.get("ship_allowed"),
        "skills_pin": result.get("skills_pin"),
    }, indent=2))
