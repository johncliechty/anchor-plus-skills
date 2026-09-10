"""Fake transports need no installed model; real transports retain their policy."""

from pathlib import Path

import pytest

import job_runner
import model_policy
import terminal_session
from tests.test_terminal_session import env as terminal_env


def _unavailable(family, **kwargs):
    raise model_policy.PolicyUnavailable(family, "synthetic unavailable provider")


@pytest.mark.parametrize("family", ["claude", "gemini", "grok"])
def test_overridden_runner_needs_no_installed_provider(tmp_path, monkeypatch, family):
    monkeypatch.setenv("ANCHOR_DATA_DIR", str(tmp_path))
    fake = Path(__file__).parent / "fake_claude.py"
    monkeypatch.setenv("ANCHOR_RUNNER_CMD", f"python {fake.resolve().as_posix()}")
    monkeypatch.setattr(model_policy, "resolve", _unavailable)
    rec = job_runner.launch(
        "research", cwd=str(tmp_path), backend=family,
        extra_args=["--lines", "1", "--line-interval", "0", "--sleep", "0"])
    try:
        result = job_runner.wait(rec["job_id"], timeout=10)
        assert result["status"] == job_runner.STATUS_DONE, result
        assert result["model_policy"] is None
        assert "fake-line 0" in "\n".join(job_runner.all_lines(rec["job_id"]))
    finally:
        job_runner.cancel(rec["job_id"])


@pytest.mark.parametrize("family", ["claude", "gemini", "grok", "chatgpt"])
def test_stub_terminal_runs_without_provider_capabilities(terminal_env, monkeypatch, family):
    monkeypatch.setattr(model_policy, "resolve", _unavailable)
    ts = terminal_env["ts"]
    rec = ts.start_session(terminal_env["pid"], "research", backend=family)
    try:
        assert rec["session_id"] in terminal_env["pty"].live_sessions()
        assert rec.get("model_policy") is None
    finally:
        ts.kill(rec["session_id"], project_id=terminal_env["pid"])


@pytest.mark.parametrize("pty_backend", ["", "native", "stub-typo"])
def test_real_terminal_still_refuses_unavailable_policy(monkeypatch, pty_backend):
    monkeypatch.setenv("ANCHOR_PTY_BACKEND", pty_backend)
    monkeypatch.setattr(model_policy, "resolve", _unavailable)
    with pytest.raises(terminal_session.TerminalSessionError, match="synthetic unavailable"):
        terminal_session._resolve_model_selection("claude", settings={})


@pytest.mark.parametrize("family", ["claude", "chatgpt"])
def test_real_runner_still_refuses_unavailable_policy(tmp_path, monkeypatch, family):
    monkeypatch.setenv("ANCHOR_DATA_DIR", str(tmp_path))
    if family == "claude":
        monkeypatch.delenv("ANCHOR_RUNNER_CMD", raising=False)
    # For ChatGPT leave the generic override set: it cannot replace its adapter.
    monkeypatch.setattr(model_policy, "resolve", _unavailable)

    def forbidden(*args, **kwargs):
        raise AssertionError("No command may resolve after policy refusal")

    monkeypatch.setattr(job_runner, "resolve_runner_cmd", forbidden)
    with pytest.raises(model_policy.PolicyUnavailable, match="synthetic unavailable"):
        job_runner.launch("research", backend=family, cwd=str(tmp_path),
                          output_dir=str(tmp_path), permission_mode="plan")
