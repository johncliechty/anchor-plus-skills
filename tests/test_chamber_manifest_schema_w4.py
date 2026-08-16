# W4 stub gate — the versioned pipeline-manifest schema (F2).
#
# AUTH-ON: not-a-surface
#
# Names + exercises the persistence surface chamber/manifest-schema.json:
# the schema document itself, the derive→validate→write→load round trip
# against it, the schema_version law, and the E9 distinct-stages law.
# Pure schema/manifest logic — no server is ever booted here.
import json
import sys
from pathlib import Path

import pytest

ANCHOR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ANCHOR))

import chamber_manifest as cm  # noqa: E402

SCHEMA_FILE = ANCHOR / "chamber" / "manifest-schema.json"


def test_manifest_schema_document_exists_versioned_and_owned():
    # chamber/manifest-schema.json is a real, versioned, owner-declared document
    doc = json.loads(SCHEMA_FILE.read_text(encoding="utf-8"))
    assert doc["schema_version"] == cm.SCHEMA_VERSION
    assert doc["owner_file"] == "chamber_manifest.py"
    # every schema_version ever shipped keeps a migration note (F2 evolution law)
    noted = {n["schema_version"] for n in doc["migration_notes"]}
    assert cm.SCHEMA_VERSION in noted


def test_load_schema_reads_the_committed_document():
    sch = cm.load_schema()
    assert sch["schema_version"] == cm.SCHEMA_VERSION
    assert sch["artifact"] == "chamber-pipeline-manifest-schema"


def test_derive_validate_write_load_round_trip(tmp_path):
    steps = [{"id": "s1", "title": "Draft the memo", "skill": "gandalf"}]
    manifest = cm.derive_manifest_for_scaffold(steps, "prop-123")
    assert cm.validate_manifest(manifest) == []
    cm.write_manifest(tmp_path, manifest)
    loaded = cm.load_manifest(tmp_path)
    assert loaded == manifest
    # canonical hash is stable across the write/load boundary
    assert cm.compute_manifest_hash(loaded) == cm.compute_manifest_hash(manifest)


def test_schema_version_mismatch_is_rejected():
    manifest = cm.derive_manifest_for_scaffold(
        [{"id": "s1", "title": "T", "skill": "gandalf"}], "prop-v")
    manifest["schema_version"] = 999
    problems = cm.validate_manifest(manifest)
    assert problems, "a manifest on an undeclared schema_version must not validate"


def test_e9_distinct_stages_enforced_per_step():
    manifest = cm.derive_manifest_for_scaffold(
        [{"id": "s1", "title": "T", "skill": "gandalf"}], "prop-e9")
    manifest["steps"][0].pop("stages", None)
    problems = cm.validate_manifest(manifest)
    assert problems, "a step without its E9 distinct stages must not validate"
