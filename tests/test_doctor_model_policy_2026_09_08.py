"""Doctor must resolve its selected provider before any model launch."""
import importlib
import json
from pathlib import Path

import pytest


class Reply:
    def _send_json(self, body, status=200):
        self.body, self.status = body, status


@pytest.fixture
def doctor(tmp_path, monkeypatch):
    monkeypatch.setenv("ANCHOR_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path / "profile"))
    import paths
    importlib.reload(paths)
    import anchor_settings
    importlib.reload(anchor_settings)
    settings = anchor_settings.save_settings(default_cli="chatgpt", coding_family="chatgpt", review_family="grok")
    import anchor_gui as gui
    monkeypatch.setattr(gui._lanes, "detect_host_profile", lambda: {
        "claude": True, "chatgpt": True, "grok": True, "gemini": False})
    monkeypatch.setattr(gui, "_doctor_stats", lambda: {})
    monkeypatch.setattr(gui, "_build_doctor_seed", lambda: "Synthetic diagnosis")
    calls = []
    def start(**kwargs):
        calls.append(kwargs)
        return {"session_id": "fixture-doctor", "backend": kwargs["backend"], "status": "running"}, False
    monkeypatch.setattr(gui._termsess, "start_doctor_session", start)
    return gui, anchor_settings, calls, settings


def test_omitted_backend_uses_dashboard_chatgpt(doctor):
    gui, settings, calls, snapshot = doctor
    reply = Reply()
    gui.handle_doctor_session_start(reply, "", {})
    assert reply.status == 200 and reply.body["ok"]
    assert calls[0]["backend"] == "chatgpt"
    assert calls[0]["resolve"] is False


def test_status_retains_configured_default_when_unavailable(doctor, monkeypatch):
    gui, settings, calls, snapshot = doctor
    monkeypatch.setattr(gui._lanes, "detect_host_profile", lambda: {"chatgpt": False, "grok": True})
    reply = Reply()
    gui.handle_doctor_status(reply, "", {})
    assert reply.body["defaultEngine"] == "chatgpt"
    assert not next(row for row in reply.body["engines"] if row["id"] == "chatgpt")["enabled"]
    assert reply.body["settings_revision"] == snapshot["settings_revision"]
    assert not calls


def test_corrupt_primary_blocks_status_and_start(doctor):
    gui, settings, calls, snapshot = doctor
    settings.settings_path().write_text("{invalid", encoding="utf-8")
    reply = Reply()
    gui.handle_doctor_status(reply, "", {})
    assert not reply.body["ok"] and reply.body["defaultEngine"] is None
    assert not any(row["enabled"] for row in reply.body["engines"])
    gui.handle_doctor_session_start(reply, "", {})
    assert reply.status == 400 and reply.body["status"] == "settings_invalid"
    assert not calls


def test_stale_revision_rejected_before_spawn(doctor):
    gui, settings, calls, snapshot = doctor
    settings.save_settings(default_cli="grok")
    reply = Reply()
    gui.handle_doctor_session_start(reply, "", {"backend": "chatgpt", "settings_revision": snapshot["settings_revision"]})
    assert reply.status == 409 and not calls


def test_doctor_script_is_auth_first_and_has_no_initial_claude_choice():
    text = (Path(__file__).resolve().parents[1] / "anchor_gui.py").read_text(encoding="utf-8")
    page = text[text.index("var ZH_SETTINGS_REVISION") - 100:]
    assert "var ZH_ENG = null" in page[:100]
    assert "if (!ZH_ENG" in page
    assert "settings_revision: ZH_SETTINGS_REVISION" in page


def test_doctor_page_has_a_real_chatgpt_button():
    from html.parser import HTMLParser
    import anchor_gui
    class Buttons(HTMLParser):
        def handle_starttag(self, tag, attrs):
            if tag == "button":
                self.buttons.append(dict(attrs))
    parser = Buttons()
    parser.buttons = []
    parser.feed(anchor_gui._DOCTOR_PAGE_TEMPLATE)
    button = next(row for row in parser.buttons if row.get("id") == "engChat")
    assert button["data-eng"] == "chatgpt"
    assert button["onclick"] == "pickDoctorEng('chatgpt')"


def test_status_returns_current_issue_panel_not_a_stale_resolve_button(doctor, monkeypatch):
    gui, _, _, _ = doctor
    monkeypatch.setattr(gui, "_doctor_stats", lambda: {
        "status": "yellow", "issues": [], "warnings": ["Optional check skipped"]})
    reply = Reply()
    gui.handle_doctor_status(reply, "", {})
    assert reply.body["issues_html"] == ""
    assert reply.body["warnings"] == ["Optional check skipped"]


def test_doctor_refresh_is_read_only_and_rerun_waits_for_real_receipt():
    import anchor_gui
    page = anchor_gui._DOCTOR_PAGE_TEMPLATE
    resolve = page.split("window.resolveAll = function")[1].split("window.resolveIssue")[0]
    assert "!p.rerun || !p.rerun.ok" in resolve
    assert "pollTail(0)" in resolve
    assert "setInterval(function () { if (!document.hidden) refreshStats(); }, 15000)" in page
    assert "issuePanel.innerHTML = s.issues_html" in page
