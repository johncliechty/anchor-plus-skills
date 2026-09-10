"""Summary launches honor saved ChatGPT settings and the bundled Doctor stubs."""

import importlib
import sys
from pathlib import Path

import pytest


@pytest.fixture
def summary_stack(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))
    monkeypatch.setenv("ANCHOR_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.delenv("ANCHOR_RUNNER_CMD", raising=False)
    for name in ("paths", "anchor_settings", "job_runner", "rnd_registry",
                 "effort_history", "report_viewer", "summarizer"):
        importlib.reload(importlib.import_module(name))
    import anchor_settings
    import job_runner
    import model_policy
    import rnd_registry
    import summarizer

    anchor_settings.save_settings(coding_family="chatgpt", review_family="claude")
    model_policy._MEMORY.clear()
    monkeypatch.setattr(model_policy, "discover", lambda *_args, **_kwargs: (
        [{"model": "fixture-frontier", "efforts": ["max", "ultra"],
          "rank": 0, "upgrade": None, "evidence": "test_catalog"}], "fixture-cli"))
    fake = Path(__file__).with_name("fake_codex_adapter_unicode.py").resolve()
    monkeypatch.setattr(job_runner, "CODEX_ADAPTER_PATH", str(fake))
    launched = []
    original_popen = job_runner.subprocess.Popen

    def capture(argv, *args, **kwargs):
        # The only model process permitted by this regression is our local stub.
        if len(argv) > 1 and Path(str(argv[0])).name.lower() in ("python", "python.exe"):
            assert Path(argv[1]).resolve().parent == fake.parent
            launched.append((list(argv), kwargs))
        return original_popen(argv, *args, **kwargs)

    monkeypatch.setattr(job_runner.subprocess, "Popen", capture)
    folder = tmp_path / "project"
    folder.mkdir()
    content = "Cache validated summaries for each research session."
    (folder / "README.md").write_text(
        "# Summary project\n\n## Goal\n" + content + "\n", encoding="utf-8")
    project = rnd_registry.add_project("Summary project", str(folder))
    session = {
        "session_id": "summary-contract", "title": "Summary project",
        "provenance": "imported", "member_files": [{
            "title": "Summary project", "artifact_path": "README.md",
            "provenance": "discovered",
        }],
    }
    yield summarizer, job_runner, anchor_settings, folder, project["id"], session, launched
    for rec in job_runner.list_records():
        if rec.get("status") == job_runner.STATUS_RUNNING:
            job_runner.cancel(rec["job_id"])
    job_runner._reset_live_table_for_tests()


def _summarize(stack, kind):
    summ, _jobs, _settings, folder, pid, session, _launched = stack
    if kind == "project":
        return summ.summarize_project(folder, pid)
    return summ.summarize_session(folder, pid, "planning", session)


@pytest.mark.parametrize("kind", ["session", "project"])
def test_selected_chatgpt_summary_uses_scoped_read_only_adapter(summary_stack, kind):
    summ, jobs, settings, folder, _pid, _session, launched = summary_stack
    result = _summarize(summary_stack, kind)
    assert not result.get("error")
    assert any("validated summaries" in claim for claim in result["claims"])
    records = jobs.list_records()
    assert len(records) == summ.GENERATE_RUNS
    assert len(launched) == summ.GENERATE_RUNS
    for rec in records:
        assert rec["backend"] == "chatgpt"
        assert rec["status"] == jobs.STATUS_DONE
        assert rec["model_receipt"]["sandbox_requested"] == "read-only"
        assert rec["relaunch_spec"]["permission_mode"] == "plan"
    for argv, kwargs in launched:
        assert Path(argv[1]).name == "fake_codex_adapter_unicode.py"
        assert argv[argv.index("--sandbox") + 1] == "read-only"
        assert Path(argv[argv.index("--target") + 1]) == folder.resolve()
        assert Path(kwargs["cwd"]) == folder
        assert "--expected-artifact" not in argv
        assert not any("Summarize this" in arg for arg in argv)
    assert _summarize(summary_stack, kind)["claims"] == result["claims"]
    assert len(jobs.list_records()) == summ.GENERATE_RUNS
    assert settings.get_launch_settings()["coding_family"] == "chatgpt"


@pytest.mark.parametrize("kind", ["session", "project"])
def test_bundled_summary_stub_isolated_from_saved_family(summary_stack, monkeypatch, kind):
    summ, jobs, settings, _folder, _pid, _session, launched = summary_stack
    stub = Path(__file__).with_name("stub_summarizer.py").resolve()
    monkeypatch.setenv("ANCHOR_RUNNER_CMD", f"{sys.executable} {stub}")
    monkeypatch.setenv("STUB_SUMMARIZER_CLAIMS", "Cache validated summaries for each research session.")
    result = _summarize(summary_stack, kind)
    assert result["claims"] == ["Cache validated summaries for each research session."]
    assert len(launched) == summ.GENERATE_RUNS
    assert all(Path(argv[1]) == stub for argv, _kwargs in launched)
    assert all(rec["backend"] == "claude" for rec in jobs.list_records())
    assert settings.get_launch_settings()["coding_family"] == "chatgpt"


@pytest.mark.parametrize("command", [
    "python C:/elsewhere/stub_summarizer.py",
    "claude -p",
    "python -c pass",
])
def test_arbitrary_runner_override_keeps_saved_family(summary_stack, monkeypatch, command):
    summ, jobs, _settings, folder, _pid, _session, _launched = summary_stack
    monkeypatch.setenv("ANCHOR_RUNNER_CMD", command)
    captured = {}

    def launch(lane, **kwargs):
        captured.update(kwargs)
        return {"job_id": "captured"}

    monkeypatch.setattr(jobs, "launch", launch)
    summ._launch_summary(folder, "A bounded summary")
    assert "backend" not in captured
    assert captured["permission_mode"] == "plan"
    assert Path(captured["output_dir"]) == folder
