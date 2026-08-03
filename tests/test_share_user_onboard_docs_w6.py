"""Shareable Anchor + Skills — Wave 6 gate (docs + rights reserved).

Frozen plan (``planning/share-canonical-onboard-2026-07/IMPLEMENTATION-PLAN.md``
§Wave 6): email-ready USER-ONBOARD.md; no OSS license stamp; rights-reserved
line. Doc presence checks via ``share_ci_ship_gate``; light string markers.

Hermetic: reads repo files only; no network; no live install.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import share_ci_ship_gate as w9  # noqa: E402

REPO = Path(__file__).resolve().parent.parent
PLAN_DOC = (
    REPO / "planning" / "share-canonical-onboard-2026-07" / "USER-ONBOARD.md"
)
ROOT_DOC = REPO / "USER-ONBOARD.md"


# ── Module surface (imports real ship-gate helpers) ─────────────────────────

def test_w6_doc_helpers_importable():
    assert callable(w9.resolve_user_onboard_docs)
    assert callable(w9.check_user_onboard_doc)
    assert callable(w9.check_no_oss_license_stamp)
    assert callable(w9.check_docs_and_rights_reserved)
    assert w9.USER_ONBOARD_FILENAME == "USER-ONBOARD.md"
    assert "python -m share_onboard" in w9.USER_ONBOARD_REQUIRED_MARKERS
    assert "Package A" in w9.USER_ONBOARD_REQUIRED_MARKERS
    assert "Package B" in w9.USER_ONBOARD_REQUIRED_MARKERS
    assert "feedback" in w9.USER_ONBOARD_REQUIRED_MARKERS
    assert "anchor.ico" in w9.USER_ONBOARD_REQUIRED_MARKERS
    assert "service" in w9.USER_ONBOARD_REQUIRED_MARKERS
    assert "favicon" in w9.USER_ONBOARD_REQUIRED_MARKERS


# ── Presence (package root + planning effort) ───────────────────────────────

def test_user_onboard_md_present_at_package_and_planning():
    assert ROOT_DOC.is_file(), "package root USER-ONBOARD.md missing"
    assert PLAN_DOC.is_file(), "planning USER-ONBOARD.md missing"
    paths = w9.resolve_user_onboard_docs(REPO)
    assert paths, "resolve_user_onboard_docs found nothing"
    resolved = {p.resolve() for p in paths}
    assert ROOT_DOC.resolve() in resolved
    assert PLAN_DOC.resolve() in resolved


def test_check_user_onboard_doc_green_on_repo():
    report = w9.check_user_onboard_doc(REPO)
    assert report["ok"] is True, report.get("problems")
    assert report["rights_reserved_ok"] is True
    assert not report["missing_markers"]
    assert not report["oss_phrase_hits"]
    assert not report["problems"]


def test_check_docs_and_rights_reserved_combined():
    report = w9.check_docs_and_rights_reserved(REPO)
    assert report["ok"] is True, report.get("problems")
    assert report["user_onboard"]["ok"] is True
    assert report["no_oss_license"]["ok"] is True


# ── String markers (acceptance content) ─────────────────────────────────────

def test_user_onboard_contains_cold_start_a_b_feedback_b_icons():
    text = ROOT_DOC.read_text(encoding="utf-8")
    low = text.lower()
    assert "python -m share_onboard" in text
    assert "package a" in low
    assert "package b" in low
    assert "feedback" in low
    assert "default is no" in low or "default **no**" in low or "default no" in low
    assert "anchor.ico" in low
    assert "service" in low
    assert "favicon" in low
    assert "rights reserved" in low
    assert "not open source" in low or "not open-source" in low
    # Not an OSS grant
    assert "licensed under the mit" not in low
    assert "spdx-license-identifier: mit" not in low


def test_planning_copy_has_same_required_markers():
    text = PLAN_DOC.read_text(encoding="utf-8")
    low = text.lower()
    for marker in w9.USER_ONBOARD_REQUIRED_MARKERS:
        assert marker.lower() in low, "planning copy missing marker: %s" % marker
    assert any(m in low for m in w9.USER_ONBOARD_RIGHTS_MARKERS)


# ── No OSS LICENSE stamp ────────────────────────────────────────────────────

def test_no_oss_license_file_at_repo_root():
    report = w9.check_no_oss_license_stamp(REPO)
    assert report["ok"] is True, report
    assert report["license_files"] == []
    for name in w9.OSS_LICENSE_FILENAMES:
        assert not (REPO / name).is_file(), "unexpected LICENSE stamp: %s" % name


def test_missing_doc_fails_closed(tmp_path):
    empty = tmp_path / "empty_repo"
    empty.mkdir()
    report = w9.check_user_onboard_doc(empty)
    assert report["ok"] is False
    assert "user_onboard_doc_missing" in report["problems"]


def test_incomplete_doc_fails_markers(tmp_path):
    home = tmp_path / "partial"
    home.mkdir()
    (home / "USER-ONBOARD.md").write_text(
        "# stub\n\nAll rights reserved. Not open source.\n",
        encoding="utf-8",
    )
    report = w9.check_user_onboard_doc(home)
    assert report["ok"] is False
    assert "user_onboard_marker_missing" in report["problems"]
    assert "python -m share_onboard" in report["missing_markers"]


def test_license_file_fails_closed(tmp_path):
    home = tmp_path / "with_license"
    home.mkdir()
    (home / "LICENSE").write_text(
        "MIT License\n\nPermission is hereby granted, free of charge...\n",
        encoding="utf-8",
    )
    # Minimal onboard doc so only the LICENSE check fails in the combined report.
    (home / "USER-ONBOARD.md").write_text(
        "\n".join([
            "# Onboard",
            "python -m share_onboard",
            "Package A",
            "Package B",
            "feedback default No",
            "anchor.ico",
            "service dual gate",
            "favicon",
            "All rights reserved. Not open source.",
            "",
        ]),
        encoding="utf-8",
    )
    lic = w9.check_no_oss_license_stamp(home)
    assert lic["ok"] is False
    assert "oss_license_file_present" in lic["problems"]
    combined = w9.check_docs_and_rights_reserved(home)
    assert combined["ok"] is False
    assert "oss_license_file_present" in combined["problems"]
