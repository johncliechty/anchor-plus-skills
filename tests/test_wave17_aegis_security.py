"""test_wave17_aegis_security.py — Wave 17 Aegis Security Vulnerability Scanner & Auto-Remediation Test Suite."""
from __future__ import annotations

import json
from pathlib import Path

from steward_cockpit import aegis_session, steward_routes
import vendor_skills


_SYNTH_TOKEN = "sk-" + ("x" * 24)
_KEY_VAR = "api" + "_key"

VULNERABLE_SAMPLE = f'''import hashlib
import os
import subprocess
import urllib.request
import yaml

{_KEY_VAR} = "{_SYNTH_TOKEN}"

def run_cmd(user_cmd):
    return subprocess.run(user_cmd, shell=True)

def parse_cfg(raw_yaml):
    val = eval("1 + 2")
    return yaml.load(raw_yaml)

def read_user_file(base_dir, rel_name):
    with open(os.path.join(base_dir, rel_name)) as fh:
        return fh.read()

def fetch_remote(dynamic_url):
    return urllib.request.urlopen(dynamic_url).read()

def check_auth(secret_token, expected_token, user_password):
    digest = hashlib.md5(user_password.encode()).hexdigest()
    if secret_token == expected_token:
        return digest
    return ""
'''


def test_aegis_engine_detects_all_six_cwe_families():
    eng = aegis_session._load_aegis_engine()
    findings = eng.scan_python_source(VULNERABLE_SAMPLE, rel_path="vuln_app.py")
    rule_ids = {f["rule_id"] for f in findings}
    assert {"AEG-01", "AEG-02", "AEG-03", "AEG-04", "AEG-05", "AEG-06"} <= rule_ids


def test_aegis_auto_remediation_applies_valid_python_patches(tmp_path: Path):
    vuln_file = tmp_path / "service.py"
    vuln_file.write_text(VULNERABLE_SAMPLE, encoding="utf-8")

    scan_res = aegis_session.run_cockpit_aegis_scan(tmp_path)
    assert scan_res["ok"] is True
    assert scan_res["session"]["scan"]["verdict"] == "BLOCK"
    assert scan_res["session"]["scan"]["auto_fixable_count"] >= 5
    assert (tmp_path / "AEGIS-SECURITY-REPORT.md").is_file()

    # Verify frontier model seating stamp
    seating = scan_res["session"]["model_seating"]
    assert seating["coding_model_id"] == "gemini-4-argon"
    assert seating["review_model_id"] == "claude-fable-5-1"

    # Apply auto-remediation
    rem_res = aegis_session.run_cockpit_aegis_remediate(tmp_path, apply=True)
    assert rem_res["ok"] is True
    assert rem_res["session"]["last_remediation"]["applied"] is True
    assert rem_res["session"]["last_remediation"]["patches_count"] >= 5

    patched_code = vuln_file.read_text(encoding="utf-8")
    assert "shell=False" in patched_code
    assert "ast.literal_eval(" in patched_code
    assert "yaml.safe_load(" in patched_code
    assert "hmac.compare_digest(" in patched_code
    assert 'os.environ.get("API_KEY"' in patched_code


def test_aegis_auto_binds_to_anvil_session_and_builds_bucket_matrix(tmp_path: Path):
    cockpit_dir = tmp_path / "My Refactoring Cockpit"
    code_dir = tmp_path / "app_code"
    cockpit_dir.mkdir()
    code_dir.mkdir()
    (code_dir / "core.py").write_text("def compute_pure(x: int) -> int:\n    return x * 2\n", encoding="utf-8")

    # Simulate an active Anvil session inside the cockpit pointing to code_dir
    anvil_dir = cockpit_dir / ".anvil"
    anvil_dir.mkdir()
    anvil_sess_data = {
        "schema": "anchor-anvil-session/v1",
        "software": {"spec": str(code_dir), "path": str(code_dir)},
        "code_map": {
            "total_modules": 1,
            "total_functions": 1,
            "conceptual_buckets": [
                {
                    "id": "bucket-core",
                    "name": "Essential Compute Core",
                    "stage": "compute",
                    "description": "Pure arithmetic core.",
                    "member_files": ["core.py"],
                }
            ],
        },
    }
    (anvil_dir / "session.json").write_text(json.dumps(anvil_sess_data), encoding="utf-8")

    # Opening Aegis state automatically detects Anvil's bound codebase and scans it without asking for a path
    state = aegis_session.get_cockpit_aegis_state(cockpit_dir, auto_init=True)
    assert state["ok"] is True
    assert state["active"] is True
    sess = state["session"]
    assert sess["anvil_binding"]["anvil_bound"] is True
    assert Path(sess["scan"]["target"]).resolve() == code_dir.resolve()
    assert sess["scan"]["verdict"] == "PASS"
    assert len(sess["cwe_families"]) == 6
    assert len(sess["bucket_security_matrix"]) >= 1
    assert "Essential Compute Core" in sess["bucket_security_matrix"][0]["title"]
    assert len(sess["dialogue"]) >= 1


def test_aegis_chat_in_session_and_remediation_via_chat(tmp_path: Path):
    vuln_file = tmp_path / "module.py"
    vuln_file.write_text("import subprocess\ndef run(c):\n    return subprocess.run(c, shell=True)\n", encoding="utf-8")

    chat_res = aegis_session.chat_in_aegis_session(tmp_path, "How is Stage 1 Get-Data guarded?")
    assert chat_res["ok"] is True
    dlg = chat_res["session"]["dialogue"]
    assert any(m["role"] == "user" and "Stage 1" in m["text"] for m in dlg)
    assert any(m["role"] == "assistant" and "CWE-22" in m["text"] for m in dlg)

    fix_res = aegis_session.chat_in_aegis_session(tmp_path, "Please auto-remediate all open vulnerabilities now.")
    assert fix_res["ok"] is True
    assert "shell=False" in vuln_file.read_text(encoding="utf-8")


def test_aegis_registered_in_steward_routes_and_vendor_skills():
    assert "Aegis" in steward_routes.SKILLS
    skill_names = {s[0] for s in vendor_skills.SKILL_SOURCES}
    assert "aegis" in skill_names
    assert Path(r"C:\dev\Skill Foundry\skills\aegis\SKILL.md").is_file()
    assert Path(r"C:\dev\Skill Foundry\skills\aegis\HUMAN.md").is_file()
    aegis_html = Path(r"C:\dev\Anchor\steward_cockpit\static\aegis.html")
    v1_html = Path(r"C:\dev\Anchor\steward_cockpit\static\v1.html")
    anvil_html = Path(r"C:\dev\Anchor\steward_cockpit\static\anvil.html")
    assert aegis_html.is_file()
    assert "data-aegis-takeover" in v1_html.read_text(encoding="utf-8")
    assert "btnOpenAegisWorkbench" in anvil_html.read_text(encoding="utf-8")
