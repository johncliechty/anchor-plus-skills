"""Two-lane step 3 (John 2026-10-06, "build 3 anyway"): a project steward is fenced to its effort folder; skills run
as server-started skill jobs. Hermetic: no model is launched, no server is touched."""
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from steward_cockpit import codex_turn_bridge as bridge  # noqa: E402
from steward_cockpit import skill_jobs as sj  # noqa: E402
from steward_cockpit import steward_engine as se  # noqa: E402


def test_the_claude_fence_allows_reads_folder_edits_and_the_hand_off_tools_only():
    tools = se.FENCE_ALLOWED_TOOLS
    assert "Read" in tools and "Edit(./**)" in tools
    assert "Bash" not in tools and "Edit" not in tools and "Write" not in tools, "never a bare write or shell rule"
    assert "Bash(python C:/dev/Anchor/tools/steward_code_job.py *)" in tools
    assert "Bash(python C:/dev/Anchor/tools/steward_skill.py *)" in tools
    src = open(se.__file__, encoding="utf-8").read()
    assert '["--setting-sources", "project", "--permission-mode", "default",' in src, "the user's allow-all settings never load"
    assert 'fenced = STEWARD_FENCE and not self.general and self.cli == "claude"' in src,         "terminals, code jobs and (since 2026-10-06 evening: the Codex sandbox fails under the service) ChatGPT stewards keep full access"
    assert "persona += FENCE_NOTE" in src and "steward_skill.py start" in se.FENCE_NOTE


def test_the_chatgpt_fence_is_the_folder_sandbox_with_localhost():
    argv = bridge.build_argv("codex", model="m", effort="high", permission_mode="fenced")
    assert 'sandbox_mode="workspace-write"' in argv
    assert "sandbox_workspace_write.network_access=true" in argv
    assert "sandbox_workspace_write.exclude_tmpdir_env_var=true" in argv
    assert 'windows.sandbox="unelevated"' in argv
    full = bridge.build_argv("codex", model="m", effort="high", permission_mode="bypassPermissions")
    assert "sandbox_workspace_write.network_access=true" not in full


def test_a_skill_job_accepts_only_a_skill_script(tmp_path, monkeypatch):
    root = tmp_path / "skills"
    (root / "gandalf").mkdir(parents=True)
    script = root / "gandalf" / "run.py"
    script.write_text("print('ran')\n", encoding="utf-8")
    other = tmp_path / "evil.py"
    other.write_text("print('no')\n", encoding="utf-8")
    monkeypatch.setenv("ANCHOR_SKILL_ROOTS", str(root))
    assert sj.validate(["python", str(script)]) == (True, "")
    assert not sj.validate(["python", str(other)])[0]
    assert not sj.validate(["cmd", "/c", str(script)])[0]
    assert not sj.validate(["python"])[0]
    assert not sj.validate("python run.py")[0]


def test_a_skill_job_runs_in_the_folder_and_is_recorded(tmp_path, monkeypatch):
    root = tmp_path / "skills"
    root.mkdir()
    script = root / "hello.py"
    script.write_text("import os\nprint('hello from', os.path.basename(os.getcwd()))\n", encoding="utf-8")
    monkeypatch.setenv("ANCHOR_SKILL_ROOTS", str(root))
    monkeypatch.setattr(sj, "_report", lambda cdir, job: None)
    cdir = tmp_path / "effort"
    cdir.mkdir()
    out = sj.start(str(cdir), [sys.executable, str(script)], "hello")
    assert out["ok"], out
    for _ in range(100):
        job = sj.read_jobs(str(cdir))[out["job"]]
        if job["status"] != "running":
            break
        time.sleep(0.1)
    assert job["status"] == "done" and job["rc"] == 0
    assert "hello from effort" in (cdir / job["log"]).read_text(encoding="utf-8")
    assert json.loads((cdir / sj.JOBS_FILE).read_text(encoding="utf-8"))[out["job"]]["label"] == "hello"
