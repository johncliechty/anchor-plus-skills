#!/usr/bin/env python3
"""Deterministic unit & integration tests for Aegis (`scripts/aegis_engine.py`)."""
from __future__ import annotations

from pathlib import Path
import sys

SCRIPT_DIR = Path(__file__).resolve().parent.parent / "scripts"
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import aegis_engine  # noqa: E402


def _make_vulnerable_sample(tmp_path: Path) -> Path:
    sample = tmp_path / "vuln_sample.py"
    sample.write_text(
        "import hashlib\n"
        "import subprocess\n"
        "import urllib.request\n"
        "import yaml\n\n"
        "API_SECRET = '<secret>'\n\n"
        "def run_cmd(user_cmd: str, auth_token: str, expected_token: str, url: str, raw_yaml: str):\n"
        "    subprocess.run(user_cmd, shell=True)\n"
        "    data = yaml.load(raw_yaml)\n"
        "    if auth_token == expected_token:\n"
        "        digest = hashlib.md5(auth_token.encode()).hexdigest()\n"
        "        urllib.request.urlopen(url)\n"
        "        return data, digest\n"
        "    return None\n",
        encoding="utf-8",
    )
    return sample


def test_scan_detects_all_configured_cwe_families(tmp_path: Path) -> None:
    sample = _make_vulnerable_sample(tmp_path)
    report = aegis_engine.scan_target(sample)
    assert report["schema"] == "aegis-security-report/v1"
    rule_ids = {f["rule_id"] for f in report["findings"]}
    assert "AEG-01" in rule_ids
    assert "AEG-02" in rule_ids
    assert "AEG-04" in rule_ids
    assert "AEG-05" in rule_ids
    assert "AEG-06" in rule_ids


def test_remediate_preview_and_apply_closes_fixable_findings(tmp_path: Path) -> None:
    sample = _make_vulnerable_sample(tmp_path)
    preview = aegis_engine.remediate_target(sample, apply=False)
    assert preview["schema"] == "aegis-remediation/v1"
    assert preview["applied"] is False
    assert preview["patches_count"] >= 1
    # Preview must not mutate file on disk
    assert "shell=True" in sample.read_text(encoding="utf-8")

    applied = aegis_engine.remediate_target(sample, apply=True, rule_filter="AEG-01")
    assert len(applied["files_modified"]) == 1
    updated_src = sample.read_text(encoding="utf-8")
    assert "shell=False" in updated_src
    assert "shell=True" not in updated_src
