"""John 2026-10-10: a cockpit never changes Anchor's own code (he makes those changes from outside Anchor), and a code
job's processes never carry Anchor's key."""
import os
import sys

import anchor_settings
from steward_cockpit import code_jobs
from steward_cockpit import steward_engine as se


def test_every_steward_is_told_the_rule():
    for duty in (se.SMALL_DUTY, se.EFFORT_DUTY):
        assert "never changed from a cockpit" in duty
    assert "any change to an Anchor application file" not in se.SMALL_DUTY


def test_a_code_jobs_commands_never_carry_the_key(tmp_path, monkeypatch):
    monkeypatch.setenv("ANCHOR_TOKEN", "secret-for-test")
    out = tmp_path / "out.txt"
    with out.open("wb") as fh:
        run = code_jobs._popen_contained([sys.executable, "-c", "import os; print(os.environ.get('ANCHOR_TOKEN'))"],
                                         str(tmp_path), dict(os.environ), fh)
        run.proc.wait(timeout=60)
        if run.wjob is not None:
            run.wjob.close()
    assert out.read_text().strip() == "None"


def test_a_coder_never_carries_the_key_but_a_steward_does(tmp_path, monkeypatch):
    monkeypatch.setenv("ANCHOR_TOKEN", "secret-for-test")
    monkeypatch.setattr(se, "STATE_FILE", tmp_path / "state.json")
    monkeypatch.setattr(anchor_settings, "load_settings", lambda: {"default_cli": "claude", "settings_revision": 1})
    eng = se.Engine(str(tmp_path), fake=True)
    assert eng._spawn_env().get("ANCHOR_TOKEN") == "secret-for-test"      # stewards start jobs with it
    eng.code_job = {"cdir": str(tmp_path), "id": "x"}
    assert "ANCHOR_TOKEN" not in eng._spawn_env()


def test_no_duty_text_still_sends_anchor_changes_to_a_code_job():
    for text in (se.CONTRACT, se.SMALL_DUTY, se.EFFORT_DUTY, se.SERVED_READ_ONLY_NOTE):
        assert "Anchor application file" not in text and "lands on anchor-next" not in text
    assert "never changed from a cockpit" in se.CONTRACT


def test_an_older_job_on_anchor_is_never_landed_or_recovered(monkeypatch):
    import anchor_next
    monkeypatch.delenv("ANCHOR_SERVED_CODE_JOBS", raising=False)
    monkeypatch.setattr(anchor_next, "is_served_repo", lambda repo: True)
    why = code_jobs.integration_required_error({"repo": "C:/dev/Anchor", "land_to": "C:/somewhere/anchor-next"})
    assert "never changed from a cockpit" in why


def test_a_foreman_wrapper_is_never_a_skill_job(tmp_path, monkeypatch):
    from steward_cockpit import skill_jobs
    wrapper = tmp_path / "ramanujan" / "run-foreman.mjs"
    wrapper.parent.mkdir()
    wrapper.write_text("//")
    monkeypatch.setattr(skill_jobs, "skill_roots", lambda: [tmp_path])
    ok, why = skill_jobs.validate(["node", str(wrapper)])
    assert not ok


def test_an_upload_never_writes_anchors_code(tmp_path, monkeypatch):
    import base64
    import anchor_gui
    monkeypatch.setattr(anchor_gui, "ANCHOR_DIR", tmp_path)
    sent = []
    h = type("H", (), {"_send_json": lambda self, d, *a: sent.append(d)})()
    data = base64.b64encode(b"x").decode()
    for name in ("anchor_gui.py", "../anchor_gui.py"):
        anchor_gui.handle_upload(h, "/api/upload", {"project_id": "dev", "filename": name, "content_b64": data})
        assert sent[-1]["ok"] is False
    anchor_gui.handle_upload(h, "/api/upload", {"project_id": "dev", "filename": "photo.png", "content_b64": data})
    assert sent[-1]["ok"] is True and (tmp_path / "dev" / "photo.png").exists()
    assert not (tmp_path / "anchor_gui.py").exists() and not (tmp_path / "dev" / "anchor_gui.py").exists()
