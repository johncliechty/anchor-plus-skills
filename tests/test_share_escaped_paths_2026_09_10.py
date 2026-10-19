"""Synthetic profile paths remain private across nested JSON encodings."""

import json

import pytest

import distro
import vendor_skills


def profile_path(separator, account="fixture-collaborator"):
    return separator.join(("Q:", "Users", account, "workspace", "sample.txt"))


def encoded(value, depth):
    for _ in range(depth):
        value = json.dumps(value)
    return value


def profile_findings(text):
    return [finding for finding in distro._scan_text("fixture.txt", text)
            if finding[1] == "user-profile-path"]


@pytest.mark.parametrize("separator", ["\\", "/"])
@pytest.mark.parametrize("depth", [0, 1, 2])
def test_screening_detects_plain_and_json_escaped_profile_paths(separator, depth):
    assert profile_findings(encoded(profile_path(separator), depth))


@pytest.mark.parametrize("separator", ["\\", "/"])
@pytest.mark.parametrize("depth", [1, 2])
def test_vendor_file_scrub_preserves_json_and_removes_profile_findings(tmp_path, separator, depth):
    fixture = tmp_path / "synthetic-paths.json"
    original = encoded({"path": profile_path(separator)}, depth)
    assert profile_findings(original)
    fixture.write_text(original, encoding="utf-8")

    vendor_skills._scrub_file(fixture)

    scrubbed = fixture.read_text(encoding="utf-8")
    assert list(distro._scan_text(fixture.name, scrubbed)) == []
    restored = scrubbed
    for _ in range(depth):
        restored = json.loads(restored)
    assert restored == {"path": "<path>"}


@pytest.mark.parametrize("separator", ["\\", "/"])
@pytest.mark.parametrize("depth", [0, 1, 2])
def test_screening_preserves_example_account_exemption(separator, depth):
    assert profile_findings(encoded(profile_path(separator, account="example"), depth)) == []


@pytest.mark.parametrize("separator", ["\\", "/"])
@pytest.mark.parametrize("depth", [0, 1, 2])
def test_screening_requires_a_segment_after_account_even_with_escaped_separators(separator, depth):
    account_directory = separator.join(("Q:", "Users", "fixture-collaborator")) + separator
    assert profile_findings(encoded(account_directory, depth)) == []


def test_optional_tool_manifest_exports_configurable_paths_without_host_identity(tmp_path):
    fixture = tmp_path / "tools.manifest.json"
    manifest = {
        "$schema_version": "phasef-tools-manifest/1",
        "tools": {
            "lean": {"path": profile_path("\\"), "class": "deterministic"},
            "chatgpt": {"driver_ref": "trio:chatgpt-cli", "model": None},
        },
    }
    fixture.write_text(json.dumps(manifest), encoding="utf-8")
    vendor_skills._scrub_file(fixture)
    exported = json.loads(fixture.read_text(encoding="utf-8"))
    assert exported["tools"]["lean"]["path"] == "C:/tools/ramanujan/lean.exe"
    assert exported["tools"]["chatgpt"] == manifest["tools"]["chatgpt"]
    assert "Example paths only" in exported["local_tool_setup"]
    assert list(distro._scan_text(fixture.name, fixture.read_text(encoding="utf-8"))) == []
