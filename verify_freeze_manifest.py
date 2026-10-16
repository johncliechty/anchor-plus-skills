"""verify_freeze_manifest — validate freeze placeholders vs W1 schemas (W3).

CLI/module used by publish CI and the execute/ship gate. Confirms:

* freeze-manifest + sources pin validate against W1 schemas
* freeze tags/commits remain PLACEHOLDER until post-merge
* ship_allowed stays false while placeholders remain / go-ahead absent

Does not vendor live skill trees. Stdlib only.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from share_contracts import (
    is_placeholder,
    load_data,
    load_json,
    validate_freeze_manifest_doc,
    validate_sources_pin_doc,
)
from share_sources import (
    SHIP_ALLOWED_STAMP_TEXT,
    freeze_still_placeholder,
    go_ahead_conditions_met,
)

_MODULE_DIR = Path(__file__).resolve().parent


def _load_optional(path, fallback_name):
    if path is not None:
        return load_json(path)
    return load_data(fallback_name)


def verify_freeze_manifest(
    freeze_path=None,
    sources_path=None,
    *,
    freeze_doc=None,
    sources_doc=None,
    require_placeholders: bool = True,
    concurrent_skill_run_merged: bool = False,
    john_go_ahead: bool = False,
) -> dict:
    """Validate freeze + sources pin; report ship_allowed honestly.

    Returns::

        {
          "ok": bool,                 # schema validation clean
          "problems": [str, ...],
          "ship_allowed": bool,       # false until go-ahead + real tags
          "ship_allowed_stamp_text": str,
          "freeze_placeholders": bool,
          "go_ahead": {...},
          "freeze": {summary},
          "sources": {summary},
        }
    """
    if freeze_doc is None:
        freeze_doc = _load_optional(freeze_path, "freeze_manifest")
    if sources_doc is None:
        sources_doc = _load_optional(sources_path, "sources_pin")

    problems = []
    problems.extend(
        validate_freeze_manifest_doc(
            freeze_doc, require_placeholders=require_placeholders
        )
    )
    problems.extend(
        validate_sources_pin_doc(
            sources_doc, require_placeholders=require_placeholders
        )
    )

    placeholders = freeze_still_placeholder(sources_doc)
    if isinstance(freeze_doc, dict):
        for repo, tag in (freeze_doc.get("freeze_tags") or {}).items():
            if is_placeholder(tag):
                placeholders = True
                break
        fsp = freeze_doc.get("skills_pin") or {}
        if is_placeholder(fsp.get("tag")) or is_placeholder(fsp.get("commit")):
            placeholders = True

    go_ahead = {
        "concurrent_skill_run_merged": bool(concurrent_skill_run_merged),
        "john_go_ahead": bool(john_go_ahead),
    }
    conditions = go_ahead_conditions_met(**go_ahead)

    # ship_allowed is true only when schemas ok, no placeholders, go-ahead,
    # AND both docs already claim ship_allowed (never invent true).
    docs_claim = (
        isinstance(freeze_doc, dict)
        and freeze_doc.get("ship_allowed") is True
        and isinstance(sources_doc, dict)
        and sources_doc.get("ship_allowed") is True
    )
    ship_allowed = (
        not problems
        and not placeholders
        and conditions
        and docs_claim
    )

    stamp = SHIP_ALLOWED_STAMP_TEXT
    if isinstance(sources_doc, dict) and sources_doc.get(
        "ship_allowed_stamp_text"
    ):
        stamp = sources_doc["ship_allowed_stamp_text"]

    freeze_summary = {}
    if isinstance(freeze_doc, dict):
        freeze_summary = {
            "schema": freeze_doc.get("schema"),
            "ship_allowed": freeze_doc.get("ship_allowed"),
            "package_matrix_version": freeze_doc.get("package_matrix_version"),
            "skills_pin": freeze_doc.get("skills_pin"),
            "freeze_tags": freeze_doc.get("freeze_tags"),
        }
    sources_summary = {}
    if isinstance(sources_doc, dict):
        sources_summary = {
            "schema": sources_doc.get("schema"),
            "ship_allowed": sources_doc.get("ship_allowed"),
            "skills_pin": sources_doc.get("skills_pin"),
            "package_versions": sources_doc.get("package_versions"),
            "pins": sources_doc.get("pins"),
        }

    return {
        "ok": not problems,
        "problems": problems,
        "ship_allowed": bool(ship_allowed),
        "ship_allowed_stamp_text": stamp,
        "freeze_placeholders": bool(placeholders),
        "go_ahead": go_ahead,
        "freeze": freeze_summary,
        "sources": sources_summary,
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description=(
            "Validate share freeze-manifest + sources pin against W1 schemas. "
            "ship_allowed remains false until go-ahead conditions are recorded."
        )
    )
    ap.add_argument(
        "--freeze",
        default=None,
        help="path to freeze-manifest JSON (default: shipped share_freeze_manifest.json)",
    )
    ap.add_argument(
        "--sources",
        default=None,
        help="path to sources pin JSON (default: shipped share_sources_pin.json)",
    )
    ap.add_argument(
        "--allow-real-tags",
        action="store_true",
        help="do not require PLACEHOLDER tags (post-merge verify mode)",
    )
    ap.add_argument(
        "--concurrent-skill-run-merged",
        action="store_true",
        help="record concurrent skill-run merge go-ahead condition",
    )
    ap.add_argument(
        "--john-go-ahead",
        action="store_true",
        help="record John go-ahead condition",
    )
    ap.add_argument(
        "--json",
        action="store_true",
        help="print full result JSON",
    )
    args = ap.parse_args(argv)

    result = verify_freeze_manifest(
        freeze_path=args.freeze,
        sources_path=args.sources,
        require_placeholders=not args.allow_real_tags,
        concurrent_skill_run_merged=args.concurrent_skill_run_merged,
        john_go_ahead=args.john_go_ahead,
    )

    if args.json:
        print(json.dumps(result, indent=2))
    else:
        status = "OK" if result["ok"] else "FAIL"
        print("verify_freeze_manifest: %s" % status)
        if result["problems"]:
            for p in result["problems"]:
                print("  - %s" % p)
        print("  ship_allowed: %s" % result["ship_allowed"])
        print("  freeze_placeholders: %s" % result["freeze_placeholders"])
        print("  stamp: %s" % result["ship_allowed_stamp_text"])
        ga = result["go_ahead"]
        print(
            "  go_ahead: merged=%s john=%s"
            % (
                ga.get("concurrent_skill_run_merged"),
                ga.get("john_go_ahead"),
            )
        )

    return 0 if result["ok"] else 1


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
