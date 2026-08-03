"""Bootstrap + simple collaborator docs — simple onboard shell Waves 3–4."""

from __future__ import annotations

from pathlib import Path

REPO = Path(__file__).resolve().parent.parent


def test_onboard_cmd_and_ps1_exist():
    assert (REPO / "onboard.cmd").is_file()
    assert (REPO / "onboard.ps1").is_file()
    ps1 = (REPO / "onboard.ps1").read_text(encoding="utf-8")
    assert "share_onboard" in ps1
    assert "winget" in ps1
    assert "Python" in ps1


def test_launch_anchor_dashboard_module_exists():
    assert (REPO / "launch_anchor_dashboard.py").is_file()
    body = (REPO / "launch_anchor_dashboard.py").read_text(encoding="utf-8")
    assert "ensure_dashboard_running" in body
    assert "probe_local_dashboard" in body


def test_user_onboard_leads_with_git_and_onboard_bootstrap():
    doc = (REPO / "USER-ONBOARD.md").read_text(encoding="utf-8")
    assert "git clone" in doc.lower() or "git clone" in doc
    assert "onboard.cmd" in doc or "onboard.ps1" in doc
    assert "C:\\dev" in doc or "C:\\dev" in doc.replace("/", "\\")
    # Cold-start is bootstrap, not slash-onboard first
    assert "python -m share_onboard" in doc or "onboard.cmd" in doc
    assert "/onboard" in doc  # still mentioned as post-install


def test_desktop_shortcut_can_target_launcher():
    import share_onboard as sob

    assert hasattr(sob, "desktop_shortcut_launcher_args")
    args = sob.desktop_shortcut_launcher_args(
        package_root=REPO,
        python_exe="python",
    )
    joined = "%s %s" % (args.get("target_path", ""), args.get("arguments", ""))
    assert "launch_anchor_dashboard.py" in joined
    assert args.get("working_directory")
