"""Shareable Anchor + Skills — Wave 3 gate.

Frozen plan (``planning/share-anchor-skills-2026-07/IMPLEMENTATION-PLAN.md``
§Wave 3): SOURCES.md multi-repo provenance writer; publish pipeline asserts
(A|B only, B contains A, dirty-tree block, skills_pin); verify_freeze_manifest;
full-roster canary path (still freeze-gated); pin-mismatch degraded code for
onboard; CI job bodies for dirty-tree / matrix / B_contains_A.

Hermetic: no network, no paid CLI, no :8777, no live git publish. Dirty-tree
and git status are injected; package trees are temp dirs.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import share_contracts as sc  # noqa: E402
import share_publish as pub  # noqa: E402
import share_sources as src  # noqa: E402
import verify_freeze_manifest as vfm  # noqa: E402

REPO = Path(__file__).resolve().parent.parent


# ── Modules + shipped freeze data ────────────────────────────────────────────

# v1.2.5 (2026-08-25): the SHIPPED freeze records are released (real pins,
# ship_allowed true, John's go-ahead stamped). The placeholder LAW — nothing
# ships while placeholders remain / without go-ahead — is still enforced by
# the code and still tested here, but against these SYNTHETIC pre-release
# docs, not the shipped files.
_PLACEHOLDER_SOURCES_DOC = {
    "schema": "share-sources-pin/v1",
    "schema_version": 1,
    "ship_allowed": False,
    "ship_allowed_stamp_text": (
        "only after concurrent skill-run merge + John go-ahead"
    ),
    "skills_pin": {"tag": "PLACEHOLDER", "commit": "PLACEHOLDER"},
    "pins": [
        {"repo": "anchor", "tag": "PLACEHOLDER", "commit": "PLACEHOLDER"},
        {"repo": "trio", "tag": "PLACEHOLDER", "commit": "PLACEHOLDER"},
        {"repo": "skill-foundry", "tag": "PLACEHOLDER",
         "commit": "PLACEHOLDER"},
    ],
    "package_versions": {"A": "0.0.0-placeholder", "B": "0.0.0-placeholder"},
    "scrub_tool_versions": {"vendor_skills.py": "GREEN-share-distro",
                            "distro.py": "GREEN-share-distro"},
}

_PLACEHOLDER_FREEZE_DOC = {
    "schema": "share-freeze-manifest/v1",
    "schema_version": 1,
    "ship_allowed": False,
    "skills_pin": {"tag": "PLACEHOLDER", "commit": "PLACEHOLDER"},
    "freeze_tags": {
        "anchor": "PLACEHOLDER",
        "trio": "PLACEHOLDER",
        "skill-foundry": "PLACEHOLDER",
    },
    "package_matrix_version": "0.0.0-placeholder",
}


def test_w3_modules_importable():
    assert callable(src.write_sources_md)
    assert callable(src.build_attestation)
    assert callable(pub.evaluate_publish_gates)
    assert callable(pub.publish_or_refuse)
    assert callable(pub.check_b_contains_a)
    assert callable(pub.ci_dirty_tree_block)
    assert callable(pub.ci_matrix_assert)
    assert callable(pub.ci_b_contains_a)
    assert callable(vfm.verify_freeze_manifest)
    assert callable(vfm.main)


def test_shipped_freeze_and_sources_released():
    freeze = sc.load_data("freeze_manifest")
    sources = sc.load_data("sources_pin")
    assert freeze["ship_allowed"] is True
    assert sources["ship_allowed"] is True
    assert sc.validate_freeze_manifest_doc(
        freeze, require_placeholders=False
    ) == []
    assert sc.validate_sources_pin_doc(
        sources, require_placeholders=False
    ) == []
    assert src.freeze_still_placeholder(sources) is False


# ── GWT: dirty tree mid skill-run → publish fails before any write ───────────

def test_given_dirty_tree_when_publish_then_fails_before_artifact_written():
    """GWT #1: dirty working tree blocks publish; no artifact written."""
    written = []

    def _write(_decision):
        written.append("artifact")
        return "would-write"

    request = {
        "artifact_name": "skills-only",
        "package_id": "A",
        "skills_subtree_present": True,
    }
    with pytest.raises(pub.PublishGateError) as ei:
        pub.publish_or_refuse(
            request,
            write_artifact_fn=_write,
            status_text=" M vendor_skills.py\n",
        )
    assert "dirty_working_tree" in ei.value.reason_codes
    assert written == [], "must not write any artifact when dirty"

    # evaluate_publish_gates alone also reports dirty first.
    codes = pub.evaluate_publish_gates(
        request, status_text="?? untracked.txt\n"
    )
    assert codes == ["dirty_working_tree"]


def test_clean_tree_allows_non_public_publish_without_write():
    request = {
        "artifact_name": "skills-only",
        "package_id": "A",
        "skills_subtree_present": True,
    }
    decision = pub.publish_or_refuse(
        request,
        write_artifact_fn=None,
        status_text="",  # clean
        public_tag_attempt=False,
    )
    assert decision["emit"] is True
    assert decision["package_id"] == "A"
    assert decision["reason_codes"] == []


def test_ci_dirty_tree_block_job():
    dirty = pub.ci_dirty_tree_block(status_text=" M foo.py\n")
    assert dirty["ok"] is False
    assert "dirty_working_tree" in dirty["reason_codes"]
    clean = pub.ci_dirty_tree_block(status_text="")
    assert clean["ok"] is True
    assert clean["reason_codes"] == []


# ── GWT: B_contains_A checksum equality for same skills_pin ──────────────────

def _write_skills_tree(root: Path, files: dict):
    root.mkdir(parents=True, exist_ok=True)
    for rel, body in files.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(body, encoding="utf-8")


def test_given_a_and_b_same_pin_when_b_contains_a_then_checksums_equal(tmp_path):
    """GWT #2: skills subtree checksum in B equals A for the pin."""
    pin = {"tag": "PLACEHOLDER", "commit": "PLACEHOLDER"}
    content = {
        "foreman/SKILL.md": "# Foreman\n",
        "foreman/src/run.mjs": "export const ok = true;\n",
        "crucible/SKILL.md": "# Crucible\n",
    }
    a_root = tmp_path / "pkgA" / "skills"
    b_root = tmp_path / "pkgB" / "skills"
    _write_skills_tree(a_root, content)
    _write_skills_tree(b_root, content)

    codes = pub.check_b_contains_a(a_root, b_root, skills_pin=pin)
    assert codes == []
    job = pub.ci_b_contains_a(a_root, b_root, skills_pin=pin)
    assert job["ok"] is True
    assert job["checksum_a"] == job["checksum_b"]
    assert job["reason_codes"] == []


def test_b_contains_a_mismatch_when_skills_differ(tmp_path):
    pin = {"tag": "PLACEHOLDER", "commit": "PLACEHOLDER"}
    a_root = tmp_path / "A"
    b_root = tmp_path / "B"
    _write_skills_tree(a_root, {"s/SKILL.md": "A\n"})
    _write_skills_tree(b_root, {"s/SKILL.md": "B-different\n"})
    codes = pub.check_b_contains_a(a_root, b_root, skills_pin=pin)
    assert codes == ["b_contains_a_mismatch"]
    job = pub.ci_b_contains_a(a_root, b_root, skills_pin=pin)
    assert job["ok"] is False


def test_publish_gates_enforce_b_contains_a(tmp_path):
    a_root = tmp_path / "A"
    b_root = tmp_path / "B"
    _write_skills_tree(a_root, {"x.md": "same\n"})
    _write_skills_tree(b_root, {"x.md": "same\n"})
    request = {
        "artifact_name": "anchor-skills",
        "package_id": "B",
        "skills_subtree_present": True,
        "skills_pin": {"tag": "PLACEHOLDER", "commit": "PLACEHOLDER"},
    }
    codes = pub.evaluate_publish_gates(
        request,
        status_text="",
        package_a_skills_root=a_root,
        package_b_skills_root=b_root,
        public_tag_attempt=False,
    )
    assert codes == []

    _write_skills_tree(b_root, {"x.md": "diverged\n"})
    codes = pub.evaluate_publish_gates(
        request,
        status_text="",
        package_a_skills_root=a_root,
        package_b_skills_root=b_root,
        public_tag_attempt=False,
    )
    assert "b_contains_a_mismatch" in codes


# ── GWT: SOURCES.md + verify_freeze_manifest ─────────────────────────────────

def test_given_sources_md_placeholder_when_verify_then_schema_ok_ship_false(
    tmp_path,
):
    """GWT #3: SOURCES for freeze-placeholder build; ship_allowed stays false."""
    attestation = src.write_sources_md(
        tmp_path, dict(_PLACEHOLDER_SOURCES_DOC)
    )
    path = Path(attestation["path"])
    assert path.is_file()
    body = path.read_text(encoding="utf-8")

    # Required attestation fields present in the written SOURCES.md.
    assert "ship_allowed" in body
    assert "false" in body.lower() or "`false`" in body
    assert src.SHIP_ALLOWED_STAMP_TEXT in body
    assert "Multi-repo pins" in body
    assert "Package matrix versions" in body or "package" in body.lower()
    assert "Skills pin" in body
    assert "Scrub tool versions" in body
    for repo in sc.REPO_IDS:
        assert repo in body
    assert "PLACEHOLDER" in body

    pin_doc = src.attestation_as_pin_doc(attestation)
    assert pin_doc["ship_allowed"] is False
    problems = sc.validate_sources_pin_doc(
        pin_doc, require_placeholders=True
    )
    assert problems == [], problems

    result = vfm.verify_freeze_manifest(
        freeze_doc=dict(_PLACEHOLDER_FREEZE_DOC),
        sources_doc=pin_doc,
        require_placeholders=True,
    )
    assert result["ok"] is True
    assert result["problems"] == []
    assert result["ship_allowed"] is False
    assert result["freeze_placeholders"] is True
    assert "concurrent skill-run merge" in result["ship_allowed_stamp_text"]


def test_verify_freeze_manifest_ship_allowed_false_without_go_ahead():
    # The law, on synthetic pre-release docs: placeholders block ship even
    # with both go-ahead flags recorded.
    result = vfm.verify_freeze_manifest(
        freeze_doc=dict(_PLACEHOLDER_FREEZE_DOC),
        sources_doc=dict(_PLACEHOLDER_SOURCES_DOC),
        require_placeholders=True,
    )
    assert result["ok"] is True
    assert result["ship_allowed"] is False
    result2 = vfm.verify_freeze_manifest(
        freeze_doc=dict(_PLACEHOLDER_FREEZE_DOC),
        sources_doc=dict(_PLACEHOLDER_SOURCES_DOC),
        require_placeholders=True,
        concurrent_skill_run_merged=True,
        john_go_ahead=True,
    )
    assert result2["ship_allowed"] is False
    assert result2["freeze_placeholders"] is True
    # And on the RELEASED shipped docs: real tags verify clean, but the
    # go-ahead flags must still be recorded per-run — no flags, no ship.
    released = vfm.verify_freeze_manifest(require_placeholders=False)
    assert released["ok"] is True
    assert released["freeze_placeholders"] is False
    assert released["ship_allowed"] is False


def test_verify_freeze_manifest_cli_exits_zero_on_shipped(capsys):
    rc = vfm.main(["--allow-real-tags"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "OK" in out
    # Without the go-ahead flags recorded, ship stays false even on real tags.
    assert "ship_allowed: False" in out or "ship_allowed: false" in out.lower()


def test_sources_writer_never_sets_ship_allowed_with_placeholders():
    att = src.build_attestation(
        dict(_PLACEHOLDER_SOURCES_DOC),
        concurrent_skill_run_merged=True,
        john_go_ahead=True,
    )
    assert att["ship_allowed"] is False
    assert src.freeze_still_placeholder(att) is True


# ── Package matrix gates still enforced on publish path ──────────────────────

def test_anchor_only_names_fail_on_publish_path():
    request = {
        "artifact_name": "anchor-only",
        "skills_subtree_present": True,
    }
    codes = pub.evaluate_publish_gates(request, status_text="")
    assert "anchor_only_forbidden" in codes
    with pytest.raises(pub.PublishGateError) as ei:
        pub.publish_or_refuse(request, status_text="")
    assert "anchor_only_forbidden" in ei.value.reason_codes


def test_package_b_requires_skills_pin_on_publish_path():
    request = {
        "artifact_name": "anchor-skills",
        "package_id": "B",
        "skills_subtree_present": True,
    }
    codes = pub.evaluate_publish_gates(request, status_text="")
    assert "skills_pin_required" in codes


def test_ci_matrix_assert_job():
    ok = pub.ci_matrix_assert({
        "artifact_name": "skills-only",
        "package_id": "A",
        "skills_subtree_present": True,
    })
    assert ok["ok"] is True
    bad = pub.ci_matrix_assert({
        "artifact_name": "anchor-only",
        "skills_subtree_present": True,
    })
    assert bad["ok"] is False
    assert "anchor_only_forbidden" in bad["reason_codes"]


# ── Pin-mismatch degraded reason code for onboard ────────────────────────────

def test_pin_mismatch_degraded_code_defined_for_onboard():
    code = pub.pin_mismatch_degraded_code()
    assert code == "skills_pin_mismatch"
    assert code in sc.READINESS_REASON_CODES
    # readiness stamp accepts the code
    doc = {
        "schema": "share-readiness/v1",
        "schema_version": 1,
        "status": "degraded",
        "reason_codes": [code],
        "package_id": "B",
        "governance_installed": True,
        "coding_seat_ok": True,
    }
    assert sc.validate_readiness_doc(doc) == []


def test_check_skills_pin_match_detects_divergence():
    declared = {"tag": "v1.0.0", "commit": "abc123"}
    assert pub.check_skills_pin_match(declared, declared) == []
    assert pub.check_skills_pin_match(
        declared, {"tag": "v1.0.1", "commit": "abc123"}
    ) == ["skills_pin_mismatch"]
    assert pub.check_skills_pin_match(declared, None) == [
        "skills_pin_mismatch"
    ]


# ── Full-roster canary still freeze-gated ────────────────────────────────────

def test_full_roster_canary_required_before_public_tag():
    request = {
        "artifact_name": "skills-only",
        "package_id": "A",
        "skills_subtree_present": True,
    }
    # Hypothetical post-go-ahead docs (real tags + ship_allowed) still need canary.
    post_go_ahead_sources = {
        "schema": "share-sources-pin/v1",
        "schema_version": 1,
        "ship_allowed": True,
        "skills_pin": {"tag": "v1", "commit": "c" * 40},
        "pins": [
            {"repo": r, "tag": "v1", "commit": "c" * 40}
            for r in sc.REPO_IDS
        ],
        "package_versions": {"A": "1.0.0", "B": "1.0.0"},
        "scrub_tool_versions": {"distro.py": "x"},
    }
    post_go_ahead_freeze = {
        "schema": "share-freeze-manifest/v1",
        "schema_version": 1,
        "ship_allowed": True,
        "skills_pin": {"tag": "v1", "commit": "c" * 40},
        "freeze_tags": {r: "v1" for r in sc.REPO_IDS},
        "package_matrix_version": "1.0.0",
    }
    codes = pub.evaluate_publish_gates(
        request,
        status_text="",
        public_tag_attempt=True,
        canary_ok=None,
        sources_doc=post_go_ahead_sources,
        freeze_doc=post_go_ahead_freeze,
    )
    assert codes == ["canary_required"]

    codes_ok = pub.evaluate_publish_gates(
        request,
        status_text="",
        public_tag_attempt=True,
        canary_ok=True,
        sources_doc=post_go_ahead_sources,
        freeze_doc=post_go_ahead_freeze,
    )
    assert codes_ok == []


def test_full_roster_canary_required_explicit():
    codes = pub.check_full_roster_canary(public_tag_attempt=True, canary_ok=None)
    assert codes == ["canary_required"]
    assert pub.check_full_roster_canary(
        public_tag_attempt=True, canary_ok=True
    ) == []
    assert pub.check_full_roster_canary(public_tag_attempt=False) == []


def test_run_full_roster_canary_with_mocks(tmp_path):
    """Canary path uses injected vendor + clean-scan; remains freeze-gated."""

    def _fake_vendor(dest, sources=None):
        dest = Path(dest)
        skill = dest / "vendor" / "bundled-skills" / "foreman"
        skill.mkdir(parents=True)
        (skill / "SKILL.md").write_text("# ok\n", encoding="utf-8")
        return {
            "vendored": [{"name": "foreman", "commit": "abc"}],
            "skipped": [],
        }

    def _fake_scan(_dest):
        return []

    report = pub.run_full_roster_canary(
        tmp_path / "canary",
        vendor_fn=_fake_vendor,
        clean_scan_fn=_fake_scan,
    )
    assert report["ok"] is True
    assert report["ship_allowed"] is False
    assert report["freeze_gated"] is True
    assert report["clean_scan_hits"] == []


def test_public_tag_blocked_while_placeholders_even_with_canary():
    request = {
        "artifact_name": "skills-only",
        "package_id": "A",
        "skills_subtree_present": True,
    }
    codes = pub.evaluate_publish_gates(
        request,
        status_text="",
        public_tag_attempt=True,
        canary_ok=True,
        sources_doc=dict(_PLACEHOLDER_SOURCES_DOC),
        freeze_doc=dict(_PLACEHOLDER_FREEZE_DOC),
    )
    assert codes
    assert (
        "ship_not_allowed" in codes
        or "freeze_placeholders_block_ship" in codes
    )


def test_public_tag_allowed_on_released_shipped_docs():
    # The released counterpart: the SHIPPED v1.2.5 docs (real pins, go-ahead
    # stamped) clear the same public-tag gates.
    request = {
        "artifact_name": "skills-only",
        "package_id": "A",
        "skills_subtree_present": True,
    }
    codes = pub.evaluate_publish_gates(
        request,
        status_text="",
        public_tag_attempt=True,
        canary_ok=True,
        sources_doc=sc.load_data("sources_pin"),
        freeze_doc=sc.load_data("freeze_manifest"),
    )
    assert codes == [], codes


# ── Dirty wins over matrix (ordered gates) ───────────────────────────────────

def test_dirty_tree_checked_before_matrix_and_write():
    written = []

    def _write(_d):
        written.append(1)

    # Dirty + Anchor-only: should surface dirty first, never write.
    with pytest.raises(pub.PublishGateError) as ei:
        pub.publish_or_refuse(
            {"artifact_name": "anchor-only", "skills_subtree_present": True},
            write_artifact_fn=_write,
            status_text=" M x\n",
        )
    assert ei.value.reason_codes == ["dirty_working_tree"]
    assert written == []


def test_publish_reason_codes_include_w3_gates():
    for code in (
        "dirty_working_tree",
        "b_contains_a_mismatch",
        "ship_not_allowed",
        "canary_required",
        "freeze_placeholders_block_ship",
        "skills_pin_mismatch",
    ):
        assert code in pub.PUBLISH_REASON_CODES, code
