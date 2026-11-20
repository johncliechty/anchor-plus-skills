from __future__ import annotations

import json
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def test_claude_reviewer_fable_target_and_opus_agy_fallback_summary(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from copy import deepcopy
    import anchor_settings as aset
    import provider_settings as pset
    import provider_setup as ps

    monkeypatch.setenv("ANCHOR_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    full_prefs = deepcopy(pset.DEFAULT_PREFERENCES)
    full_prefs["family"] = "gemini"
    full_prefs["quality"] = {
        "claude": {"model": "latest_supported", "effort": "highest_supported"},
        "gemini": {"model": "latest_supported", "effort": "highest_supported"},
        "chatgpt": {"model": "latest_supported", "effort": "highest_supported"},
        "grok": {"model": "latest_supported", "effort": "highest_supported"},
    }
    aset.save_settings(
        default_cli="gemini",
        coding_family="gemini",
        review_family="claude",
        provider_preferences=full_prefs,
    )

    # Case 1: standalone claude CLI is signed_out, while Gemini/Antigravity (agy) is signed_in -> fallback_active True (Claude Opus 5.5)
    connections_fallback = [
        {
            "id": "claude-default",
            "family": "claude",
            "label": "Claude",
            "cli": "claude",
            "installed": True,
            "auth": "signed_out",
            "account": "",
            "plan": "",
            "note": "Not logged in",
        },
        {
            "id": "gemini-default",
            "family": "gemini",
            "label": "Gemini",
            "cli": "agy",
            "installed": True,
            "auth": "signed_in",
            "account": "Google Ultra (agy)",
            "plan": "Google AI Ultra",
            "note": "Ready via agy",
        },
        {
            "id": "chatgpt-default",
            "family": "chatgpt",
            "label": "ChatGPT",
            "cli": "codex",
            "installed": True,
            "auth": "signed_in",
            "account": "j***@g***.c***",
            "plan": "Pro",
            "note": "Signed in",
        },
        {
            "id": "grok-default",
            "family": "grok",
            "label": "Grok",
            "cli": "grok",
            "installed": True,
            "auth": "unknown",
            "account": "",
            "plan": "",
            "note": "",
        },
    ]
    prefs = {
        "family": "gemini",
        "quality": {
            "claude": {"model": "latest_supported", "effort": "highest_supported"},
            "gemini": {"model": "latest_supported", "effort": "highest_supported"},
            "chatgpt": {"model": "latest_supported", "effort": "highest_supported"},
            "grok": {"model": "latest_supported", "effort": "highest_supported"},
        },
    }
    summary = ps._build_services_and_routing_summary(connections_fallback, prefs)
    rev = summary["active_routing"]["adversarial_reviewer"]
    assert rev["family"] == "claude"
    assert "claude-fable-5-1" in rev["configured_model_display"]
    assert rev["fallback_active"] is True
    assert "Claude Opus 5.5" in rev["effective_model_display"]
    assert "agy" in rev["fallback_reason"].lower()

    # Case 2: once standalone claude CLI is signed_in -> fallback_active False, serving Fable 5.1 natively
    connections_native = [dict(c, auth="signed_in") if c["family"] == "claude" else dict(c) for c in connections_fallback]
    summary_native = ps._build_services_and_routing_summary(connections_native, prefs)
    rev_native = summary_native["active_routing"]["adversarial_reviewer"]
    assert rev_native["fallback_active"] is False
    assert "claude-fable-5-1" in rev_native["effective_model_display"]


def test_live_settings_json_targets_claude_latest_supported_not_opus() -> None:
    raw = json.loads((ROOT / "settings.json").read_text(encoding="utf-8"))
    claude_q = ((raw.get("provider_preferences") or {}).get("claude")) or (
        ((raw.get("provider_preferences") or {}).get("quality") or {}).get("claude")
    ) or {}
    # Ensure Claude is no longer pinned to legacy "opus"
    assert claude_q.get("model") in ("latest_supported", "best", "claude-fable-5-1")


def test_universal_top_right_close_x_across_overlays_collaboration_and_workbenches() -> None:
    import anchor_gui
    import gwl_admin_gui
    import onboard_wizard

    # 1. Outer Setup dialog + Cave tile deep-link in provider-controls.js
    pc_js = (ROOT / "static" / "provider-controls.js").read_text(encoding="utf-8")
    assert "provider-dialog-close-x" in pc_js
    assert "anchor-overlay-close" in pc_js
    assert "section:'providers',family:connection.family" in pc_js

    # 2. /setup HTML + JS: top-right X closes overlay and NEVER calls pywebview window_control('close')
    setup_html = (ROOT / "static" / "provider-setup.html").read_text(encoding="utf-8")
    setup_js = (ROOT / "static" / "provider-setup.js").read_text(encoding="utf-8")
    assert 'id="setup-close-x"' in setup_html
    assert 'id="logged-in-services-card"' in setup_html
    assert "if(act==='close'){leave();return;}" in setup_js
    assert "renderLoggedInServicesCard" in setup_js

    # 3. /gwl-admin and /recover-account
    admin_html = gwl_admin_gui.render_gwl_admin_gui_html(sandbox=True)
    rec_html = gwl_admin_gui.render_account_recovery_html(sandbox=True)
    assert 'id="btnCloseAdminX"' in admin_html
    assert "closeAdminOverlay" in admin_html
    assert 'id="btnCloseRecoveryX"' in rec_html
    assert "closeRecoveryOverlay" in rec_html

    # 4. /onboard-wizard
    wiz_html = onboard_wizard.render_onboard_wizard_html(sandbox=True)
    assert 'id="wizCloseOverlayX"' in wiz_html
    assert "closeWizardOverlay" in wiz_html
    assert "if (act === 'close') { closeWizardOverlay(); return; }" in wiz_html

    # 5. /doctor
    doc_html = anchor_gui.render_doctor_page_html()
    assert 'id="btnCloseDoctorX"' in doc_html
    assert "closeDoctorOverlay" in doc_html

    # 6. Anvil & Aegis Workbenches + app.js overlay return
    anvil_html = (ROOT / "steward_cockpit" / "static" / "anvil.html").read_text(encoding="utf-8")
    aegis_html = (ROOT / "steward_cockpit" / "static" / "aegis.html").read_text(encoding="utf-8")
    app_js = (ROOT / "static" / "app.js").read_text(encoding="utf-8")
    assert 'id="btnCloseWorkbenchX"' in anvil_html
    assert 'id="btnCloseWorkbenchX"' in aegis_html
    assert "anchor-overlay-close" in app_js


def test_turn_watchdog_resets_idle_on_usage_progress_and_gemini_write_tools() -> None:
    import inspect
    from steward_cockpit import codex_turn_bridge as ctb
    from steward_cockpit import gemini_turn_bridge as gtb

    assert "write_file" in gtb._WRITE_TOOLS
    assert "edit_file" in gtb._WRITE_TOOLS

    wd = ctb.TurnWatchdog(7200, 900)
    wd._last_progress = wd._started - 850.0
    before = wd._last_progress
    wd.progress()
    assert wd._last_progress > before

    turn_src = (ROOT / "steward_cockpit" / "codex_turn_bridge.py").read_text(encoding="utf-8")
    assert 'if not update.get("error") and update.get("usage") is not None:' in turn_src
    assert "watchdog.progress()" in turn_src


def test_anvil_v4_process_ranks_self_contained_runner_ahead_of_required_cli_scripts(tmp_path: Path) -> None:
    anvil_scripts = ROOT / "vendor" / "bundled-skills" / "anvil" / "scripts"
    if str(anvil_scripts) not in sys.path:
        sys.path.insert(0, str(anvil_scripts))
    import anvil_v4_process as av4p

    code_dir = tmp_path / "Code"
    code_dir.mkdir()
    # Alphabetically earlier script requiring mandatory --step3 CLI flag + sys.argv[1]
    (code_dir / "build_table2.py").write_text(
        "import argparse, sys\n"
        "def build_table(path: str) -> int:\n"
        "    return len(path)\n"
        "if __name__ == '__main__':\n"
        "    p = argparse.ArgumentParser()\n"
        "    p.add_argument('--step3', required=True)\n"
        "    args = p.parse_args()\n"
        "    print(build_table(sys.argv[1]))\n",
        encoding="utf-8",
    )
    # Root self-contained verification runner with zero required CLI flags
    (tmp_path / "run_scoped_tests.py").write_text(
        "def run_suite() -> bool:\n"
        "    return True\n"
        "if __name__ == '__main__':\n"
        "    assert run_suite()\n",
        encoding="utf-8",
    )

    pmap = av4p.build_process_map(tmp_path, persist=False)
    scenarios = pmap.get("l0_scenarios") or []
    assert len(scenarios) >= 2
    assert scenarios[0]["entry_file"] == "run_scoped_tests.py"
    assert scenarios[0]["recommended_argv"] == ["python", "run_scoped_tests.py"]
