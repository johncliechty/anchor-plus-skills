"""Regression tests for Merrill's 2026-11-06 Steward Seat Credits report:
1. When Claude CLI returns a synthetic 'credits_required' refusal (Fable 5.1 requires usage credits),
   the Steward surfaces the real provider refusal reason instead of the generic
   'I could not reach the steward's seat' message.
2. When '--model best' (Fable 5.1) fails with 'credits_required', Trio's Claude driver and
   Anchor's StewardEngine automatically step down best -> opus -> sonnet.
3. Setting provider_preferences.quality.claude.model (e.g. 'sonnet' or 'opus') in model_prefs.json /
   settings.json is honored by Trio's resolveModelPolicy, Ecgberht's callTrioSeat, and StewardEngine.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent
ECGBERHT_DIR = REPO_ROOT / "vendor" / "bundled-skills" / "ecgberht"
DRIVERS_DIR = REPO_ROOT / "vendor" / "bundled-skills" / "drivers"


def _run_node_eval(script: str, env: dict | None = None) -> dict:
    import os
    merged_env = dict(os.environ)
    if env:
        merged_env.update(env)
    proc = subprocess.run(
        ["node", "--input-type=module", "-e", script],
        cwd=str(REPO_ROOT),
        env=merged_env,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert proc.returncode == 0, f"node failed ({proc.returncode}):\nSTDOUT:\n{proc.stdout}\nSTDERR:\n{proc.stderr}"
    lines = [line.strip() for line in proc.stdout.splitlines() if line.strip()]
    assert lines, f"no stdout from node:\nSTDERR:\n{proc.stderr}"
    return json.loads(lines[-1])


def test_steward_conversation_surfaces_real_credits_required_reason():
    """Requirement 1: formatSeatUnreachableText and converseFailure surface the exact
    'Fable 5.1 requires usage credits...' refusal instead of generic 'could not reach the steward's seat'."""
    conv_url = (ECGBERHT_DIR / "engine" / "steward-conversation.mjs").as_uri()
    script = f"""
    import {{ formatSeatUnreachableText, CONVERSE_TEXT, CONVERSE_CODE }} from {json.dumps(conv_url)};
    const merrillFailure = {{
      ok: false,
      reason: 'trio_seat_failed',
      family: 'claude',
      provider_status: 'usage_limit',
      provider_error: 'Fable 5.1 requires usage credits. Switch to another model, or manage usage credits at https://claude.ai/admin-settings/usage, to continue.',
      detail: 'Trio seat seat_unavailable: claude transport unavailable (usage_limit): Fable 5.1 requires usage credits. Switch to another model, or manage usage credits at https://claude.ai/admin-settings/usage, to continue.',
    }};
    const formatted = formatSeatUnreachableText(merrillFailure, 'claude');
    const genericFailure = {{
      ok: false,
      reason: 'no_reply',
      detail: 'spawn_error',
    }};
    const genericFormatted = formatSeatUnreachableText(genericFailure, 'claude');
    console.log(JSON.stringify({{
      formatted,
      genericFormatted,
      defaultUnreachable: CONVERSE_TEXT[CONVERSE_CODE.SEAT_UNREACHABLE],
    }}));
    """
    res = _run_node_eval(script)
    assert res["formatted"] is not None
    assert "Claude refused the request:" in res["formatted"]
    assert "Fable 5.1 requires usage credits" in res["formatted"]
    assert "Nothing was written." in res["formatted"]
    assert "could not reach the steward's seat" not in res["formatted"]
    assert res["genericFormatted"] is None


def test_call_trio_seat_end_to_end_falls_back_or_surfaces_merrill_error(tmp_path):
    """Requirements 1, 2 & 3 through Ecgberht's callTrioSeat + bundled Trio drivers."""
    seat_call_url = (ECGBERHT_DIR / "scripts" / "seat-call.mjs").as_uri()
    drivers_index = str(DRIVERS_DIR / "index.mjs")

    dir_default = tmp_path / "data_default"
    dir_default.mkdir(parents=True, exist_ok=True)
    (dir_default / "settings.json").write_text(
        json.dumps({
            "coding_family": "claude",
            "review_family": "claude",
            "default_cli": "claude",
            "model_policy": {"mode": "latest_supported", "effort": "highest_supported"},
            "settings_revision": 1,
        }),
        encoding="utf-8",
    )

    dir_sonnet = tmp_path / "data_sonnet"
    dir_sonnet.mkdir(parents=True, exist_ok=True)
    (dir_sonnet / "settings.json").write_text(
        json.dumps({
            "coding_family": "claude",
            "review_family": "claude",
            "default_cli": "claude",
            "model_policy": {"mode": "latest_supported", "effort": "highest_supported"},
            "provider_preferences": {
                "quality": {
                    "claude": {"model": "sonnet", "effort": "high"},
                },
            },
            "settings_revision": 2,
        }),
        encoding="utf-8",
    )

    script = f"""
    import {{ callTrioSeat }} from {json.dumps(seat_call_url)};
    import {{ runAgent }} from {json.dumps((DRIVERS_DIR / "index.mjs").as_uri())};
    import {{ defaultRunClaude }} from {json.dumps((DRIVERS_DIR / "claude.mjs").as_uri())};
    import {{ resolveModelPolicy }} from {json.dumps((DRIVERS_DIR / "model-policy.mjs").as_uri())};

    const discoverClaude = () => ({{
      models: ['best', 'opus', 'sonnet', 'haiku'],
      efforts: ['low', 'medium', 'high', 'max'],
      version: '2.1.316 (Claude Code)',
    }});

    const envDefault = {{
      ...process.env,
      CRUCIBLE_AGENT_LIVE: '1',
      ANCHOR_DATA_DIR: {json.dumps(str(dir_default))},
      ECGBERHT_TRIO_INDEX: {json.dumps(drivers_index)},
    }};
    const envSonnet = {{
      ...process.env,
      CRUCIBLE_AGENT_LIVE: '1',
      ANCHOR_DATA_DIR: {json.dumps(str(dir_sonnet))},
      ECGBERHT_TRIO_INDEX: {json.dumps(drivers_index)},
    }};

    // Case A: best and opus return credits_required; sonnet succeeds -> automatic fallback succeeds
    const modelsTriedA = [];
    const runClaudeA = (prompt, label, opts = {{}}) => defaultRunClaude(prompt, label, {{
      ...opts,
      env: envDefault,
      policyResolver: (family, pOpts = {{}}) => resolveModelPolicy(family, {{
        ...pOpts,
        env: envDefault,
        discoverer: discoverClaude,
      }}),
      processRunner: async (req) => {{
        const idx = req.args.indexOf('--model');
        const m = idx >= 0 ? req.args[idx + 1] : null;
        modelsTriedA.push(m);
        if (m === 'best' || m === 'opus') {{
          return {{
            code: 1,
            terminal: 'closed',
            kill_status: null,
            spawned: true,
            stderr: '',
            stdout: [
              JSON.stringify({{ type: 'system', subtype: 'init', session_id: 's1', model: 'claude-fable-5-1' }}),
              JSON.stringify({{
                type: 'assistant',
                error: 'invalid_request',
                message: {{
                  model: '<synthetic>',
                  content: [{{ type: 'text', text: 'Fable 5.1 requires usage credits. Switch to another model, or manage usage credits at https://claude.ai/admin-settings/usage, to continue.' }}],
                }},
              }}),
              JSON.stringify({{
                type: 'result',
                subtype: 'success',
                is_error: true,
                num_turns: 1,
                result: 'Fable 5.1 requires usage credits. Switch to another model, or manage usage credits at https://claude.ai/admin-settings/usage, to continue.',
                api_error_status: 429,
                api_error_code: 'credits_required',
                usage: {{ input_tokens: 0, output_tokens: 0 }},
              }}),
            ].join('\\n'),
          }};
        }}
        return {{
          code: 0,
          terminal: 'closed',
          kill_status: null,
          spawned: true,
          stderr: '',
          stdout: [
            JSON.stringify({{ type: 'system', subtype: 'init', session_id: 's2', model: 'claude-sonnet-4-6' }}),
            JSON.stringify({{
              type: 'result',
              subtype: 'success',
              is_error: false,
              num_turns: 1,
              model: 'claude-sonnet-4-6',
              result: '{{"say":"Answered cleanly on Sonnet.","gathering":true,"asks":[]}}',
              modelUsage: {{ 'claude-sonnet-4-6': {{ inputTokens: 12, outputTokens: 8 }} }},
              usage: {{ input_tokens: 12, output_tokens: 8 }},
            }}),
          ].join('\\n'),
        }};
      }},
    }});

    const resA = await callTrioSeat('Hello Steward', {{
      family: 'claude',
      env: envDefault,
      runAgent: (opts) => runAgent({{ ...opts, env: envDefault, runClaude: runClaudeA }}),
    }});

    // Case B: all models fail with credits_required -> surfaces exact Fable 5.1 error message
    const runClaudeB = (prompt, label, opts = {{}}) => defaultRunClaude(prompt, label, {{
      ...opts,
      env: envDefault,
      policyResolver: (family, pOpts = {{}}) => resolveModelPolicy(family, {{
        ...pOpts,
        env: envDefault,
        discoverer: discoverClaude,
      }}),
      processRunner: async () => ({{
        code: 1,
        terminal: 'closed',
        kill_status: null,
        spawned: true,
        stderr: '',
        stdout: [
          JSON.stringify({{ type: 'system', subtype: 'init', session_id: 's1', model: 'claude-fable-5-1' }}),
          JSON.stringify({{
            type: 'result',
            subtype: 'error_during_execution',
            is_error: true,
            num_turns: 0,
            result: 'Fable 5.1 requires usage credits. Switch to another model, or manage usage credits at https://claude.ai/admin-settings/usage, to continue.',
            api_error_status: 429,
            api_error_code: 'credits_required',
            usage: {{ input_tokens: 0, output_tokens: 0 }},
          }}),
        ].join('\\n'),
      }}),
    }});

    const resB = await callTrioSeat('Hello Steward', {{
      family: 'claude',
      env: envDefault,
      runAgent: (opts) => runAgent({{ ...opts, env: envDefault, runClaude: runClaudeB }}),
    }});

    // Case C: settings.json pins provider_preferences.quality.claude.model = 'sonnet' -> launches sonnet directly
    const modelsTriedC = [];
    const runClaudeC = (prompt, label, opts = {{}}) => defaultRunClaude(prompt, label, {{
      ...opts,
      env: envSonnet,
      policyResolver: (family, pOpts = {{}}) => resolveModelPolicy(family, {{
        ...pOpts,
        env: envSonnet,
        discoverer: discoverClaude,
      }}),
      processRunner: async (req) => {{
        const idx = req.args.indexOf('--model');
        modelsTriedC.push(idx >= 0 ? req.args[idx + 1] : null);
        return {{
          code: 0,
          terminal: 'closed',
          kill_status: null,
          spawned: true,
          stderr: '',
          stdout: [
            JSON.stringify({{ type: 'system', subtype: 'init', session_id: 's3', model: 'claude-sonnet-4-6' }}),
            JSON.stringify({{
              type: 'result',
              subtype: 'success',
              is_error: false,
              num_turns: 1,
              model: 'claude-sonnet-4-6',
              result: '{{"say":"Direct Sonnet launch.","gathering":true,"asks":[]}}',
              modelUsage: {{ 'claude-sonnet-4-6': {{ inputTokens: 10, outputTokens: 5 }} }},
              usage: {{ input_tokens: 10, output_tokens: 5 }},
            }}),
          ].join('\\n'),
        }};
      }},
    }});

    const resC = await callTrioSeat('Hello Steward', {{
      family: 'claude',
      env: envSonnet,
      runAgent: (opts) => runAgent({{ ...opts, env: envSonnet, runClaude: runClaudeC }}),
    }});

    console.log(JSON.stringify({{
      modelsTriedA,
      resA,
      resB,
      modelsTriedC,
      resC,
    }}));
    """
    out = _run_node_eval(script)
    assert out["modelsTriedA"] == ["best", "opus", "sonnet"]
    assert out["resA"]["ok"] is True
    assert "Answered cleanly on Sonnet" in out["resA"]["text"]

    assert out["resB"]["ok"] is False
    assert "Fable 5.1 requires usage credits" in (out["resB"].get("provider_error") or out["resB"].get("detail") or "")

    assert out["modelsTriedC"] == ["sonnet"]
    assert out["resC"]["ok"] is True
    assert "Direct Sonnet launch" in out["resC"]["text"]


def test_python_steward_engine_credit_gate_fallback_with_api_error_code(tmp_path, monkeypatch):
    """Python Engine._try_claude_credit_gate_fallback recognizes api_error_code='credits_required'
    and steps down best -> opus -> sonnet without mutating host settings."""
    import anchor_settings
    from steward_cockpit import steward_engine

    monkeypatch.setenv("STEWARD_COCKPIT_FAKE", "1")
    monkeypatch.setenv("ANCHOR_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    monkeypatch.setattr(steward_engine, "STATE_FILE", tmp_path / "steward_state.json")

    proj_dir = tmp_path / "proj"
    proj_dir.mkdir(parents=True, exist_ok=True)

    eng = steward_engine.Engine(str(proj_dir), general=False)
    eng.cli = "claude"
    eng.model_selection = {
        "family": "claude",
        "cli": "claude",
        "model": "best",
        "effort": "high",
        "cli_args": ["--model", "best", "--effort", "high"],
    }

    # Step 1: best -> opus on api_error_code='credits_required'
    ev = {"type": "result", "is_error": True, "api_error_code": "credits_required", "api_error_status": 429}
    ok1 = eng._try_claude_credit_gate_fallback("Fable 5.1 requires usage credits.", ev=ev)
    assert ok1 is True
    assert eng.model_selection["model"] == "opus"
    assert eng.model_selection["cli_args"] == ["--model", "opus", "--effort", "high"]

    # Step 2: opus -> sonnet on api_error_code='credits_required'
    ok2 = eng._try_claude_credit_gate_fallback("Opus requires usage credits.", ev=ev)
    assert ok2 is True
    assert eng.model_selection["model"] == "sonnet"
    assert eng.model_selection["cli_args"] == ["--model", "sonnet", "--effort", "high"]

    # Step 3: sonnet -> False (end of entitlement fallback ladder)
    ok3 = eng._try_claude_credit_gate_fallback("Sonnet requires usage credits.", ev=ev)
    assert ok3 is False


def test_fence_guard_allows_escaped_quotes_and_quoted_script_path():
    """Merrill Stat 610 Attempt 1: fence_guard.py allows escaped quotes inside
    double-quoted arguments (e.g. --check "python -c \"...\"") and quoted tool paths."""
    import pytest
    from tools import fence_guard

    cmd_escaped = (
        'python C:/dev/Anchor/tools/steward_code_job.py start '
        '--effort "C:/dev/Stat 610" --repo "C:/dev/Stat 610" '
        '--prompt "Compare \\"Student A\\" and \\"Student B\\" R files" '
        '--check "python -c \\"import pathlib; assert pathlib.Path(\'similarity_report.md\').exists()\\""'
    )
    assert fence_guard.check_steward_shell(cmd_escaped) is None

    cmd_quoted_script = (
        'python "C:/dev/Anchor/tools/steward_code_job.py" status --effort "C:/dev/Stat 610"'
    )
    assert fence_guard.check_steward_shell(cmd_quoted_script) is None

    # Still blocks shell chaining outside quotes
    bad_cmd = 'python C:/dev/Anchor/tools/steward_code_job.py status --effort "C:/dev/Stat 610" && del /q *'
    with pytest.raises(SystemExit) as excinfo:
        fence_guard.check_steward_shell(bad_cmd)
    assert excinfo.value.code == 2


class _FakeJobCoder:
    def __init__(self, wt, writes):
        self.wt = wt
        self.writes = writes
        self.written_ok = []
        self.on_turn_done = None
        self.code_job = None
        self.policy_override = None
        self.cli = "claude"

    def wake(self, fresh=False, seed=None):
        for name, text in self.writes.items():
            target = Path(self.wt, name)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(text, encoding="utf-8")
            self.written_ok.append(str(target))
        self.on_turn_done({"text": "completed comparison", "error": "", "authors": ["claude"], "manifest": list(self.writes.keys())})
        return True, "awake"

    def stop(self):
        pass


def test_umbrella_git_does_not_claim_anchor_or_block_sibling_projects(tmp_path, monkeypatch):
    """Merrill Stat 610 Attempts 2 & 3:
    When an accidental umbrella .git exists at C:/dev and Anchor is installed from a zip
    at C:/dev/Anchor (without its own .git):
    - anchor_next.served_root() stays at C:/dev/Anchor (does NOT walk up to C:/dev)
    - anchor_next.is_served_repo('C:/dev') and is_served_repo('C:/dev/Stat 610') are False
    - project_bootstrap.ensure_git_repo('C:/dev') refuses to git-init the umbrella folder,
      while ensure_git_repo('C:/dev/Stat 610') initializes Stat 610's own .git even under C:/dev/.git
    - code_jobs.start() with --repo 'C:/dev' (Attempt 2) or --repo 'C:/dev/Stat 610' (Attempt 3)
      redirects/falls back to a scratch git repo seeded with Stat 610's files (including submissions/*.R),
      runs --check, and syncs outputs back to Stat 610.
    """
    import sys
    import time
    import anchor_next
    import project_bootstrap
    from steward_cockpit import code_jobs

    dev = tmp_path / "dev"
    dev.mkdir()
    # Initialize an accidental umbrella git repo at dev/
    subprocess.run(["git", "init", "-q"], cwd=str(dev), check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=str(dev), check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=str(dev), check=True)
    (dev / "umbrella.txt").write_text("root\n", encoding="utf-8")
    subprocess.run(["git", "add", "umbrella.txt"], cwd=str(dev), check=True)
    subprocess.run(["git", "commit", "-q", "-m", "umbrella init"], cwd=str(dev), check=True)

    # Zip-installed Anchor inside dev/Anchor (no .git of its own)
    fake_anchor = dev / "Anchor"
    fake_anchor.mkdir()
    (fake_anchor / "anchor_gui.py").write_text("# anchor\n", encoding="utf-8")

    # Sibling project Stat 610 (no .git of its own yet) with untracked student submissions
    stat610 = dev / "Stat 610"
    submissions = stat610 / "submissions"
    submissions.mkdir(parents=True)
    (submissions / "alice.R").write_text("x <- 42\ny <- x + 1\n", encoding="utf-8")
    (submissions / "bob.R").write_text("a <- 99\nb <- a * 2\n", encoding="utf-8")
    effort = stat610 / "midterm-check"
    effort.mkdir(parents=True)

    monkeypatch.setenv("ANCHOR_SERVED_ROOT", str(fake_anchor))
    monkeypatch.setenv("ANCHOR_CODE_JOBS_DIR", str(tmp_path / "jobs"))
    monkeypatch.setenv("ANCHOR_REVIEW_CMD", json.dumps([sys.executable, str(REPO_ROOT / "tests" / "fake_review.py")]))
    monkeypatch.setattr(code_jobs, "_report", lambda cdir, job: None)
    monkeypatch.setattr(code_jobs, "choose_coder", lambda requested="": ("claude", None))

    # 1. served_root must be fake_anchor, NOT dev
    assert anchor_next.served_root().resolve() == fake_anchor.resolve()
    assert anchor_next.is_served_repo(fake_anchor) is True
    assert anchor_next.is_served_repo(dev) is False
    assert anchor_next.is_served_repo(stat610) is False

    # 2. project_bootstrap refuses umbrella dir dev
    res_umbrella = project_bootstrap.ensure_git_repo(dev)
    assert res_umbrella["ok"] is False
    assert res_umbrella["reason"] == "umbrella-directory"

    # 3. code_jobs._repo_root ignores umbrella git at dev/
    assert code_jobs._repo_root(dev) is None
    assert code_jobs._repo_root(stat610) is None

    # 4. Attempt 2 (--repo pointing at umbrella dev/) redirects to stat610 and runs via scratch git repo
    check_argv = [
        sys.executable,
        "-c",
        "import pathlib; "
        "assert pathlib.Path('submissions/alice.R').exists(); "
        "assert pathlib.Path('submissions/bob.R').exists(); "
        "assert pathlib.Path('similarity_report.md').exists()",
    ]
    writes = {"similarity_report.md": "# No shared R files found\n"}
    started = code_jobs.start(
        str(effort),
        str(dev),
        "Check student R files in submissions/ and write similarity_report.md",
        check=check_argv,
        engine_factory=lambda wt: _FakeJobCoder(wt, writes),
    )
    assert started["ok"] is True, f"code_jobs.start failed: {started}"
    jid = started["job"]
    done_job = None
    for _ in range(200):
        j = code_jobs.read_jobs(str(effort)).get(jid) or {}
        if j.get("status") in ("done", "failed", "stopped"):
            done_job = j
            break
        time.sleep(0.05)
    assert done_job is not None and done_job["status"] == "done", f"Unexpected job outcome: {done_job}"
    assert done_job.get("landed") is True, f"Expected job to land: {done_job}"
    assert Path(done_job["non_git_source_dir"]).resolve() == stat610.resolve()
    assert (stat610 / "similarity_report.md").exists()
    assert "No shared R files found" in (stat610 / "similarity_report.md").read_text(encoding="utf-8")


def test_git_repo_project_seeds_untracked_submissions_into_worktree_and_lands_cleanly(tmp_path, monkeypatch):
    """When a project folder IS a git repo (e.g. initialized by project_bootstrap) and the user
    drops new untracked files (like submissions/*.R from Canvas) without committing them:
    - code_jobs.start() seeds those untracked files into the isolated git worktree so the coder
      and --check command can read them
    - _cleanup_unmodified_seeded_untracked removes unmodified seeded inputs before landing so
      only the coder's real deliverables land back into the project folder."""
    import sys
    import time
    import project_bootstrap
    from steward_cockpit import code_jobs

    fake_anchor = tmp_path / "Anchor"
    fake_anchor.mkdir()
    monkeypatch.setenv("ANCHOR_SERVED_ROOT", str(fake_anchor))
    monkeypatch.setenv("ANCHOR_CODE_JOBS_DIR", str(tmp_path / "jobs"))
    monkeypatch.setenv("ANCHOR_REVIEW_CMD", json.dumps([sys.executable, str(REPO_ROOT / "tests" / "fake_review.py")]))
    monkeypatch.setattr(code_jobs, "_report", lambda cdir, job: None)
    monkeypatch.setattr(code_jobs, "choose_coder", lambda requested="": ("claude", None))

    proj = tmp_path / "Stat 610 Git"
    proj.mkdir()
    (proj / "README.md").write_text("# Stat 610\n", encoding="utf-8")
    boot = project_bootstrap.ensure_git_repo(proj)
    assert boot["ok"] is True and boot["initialized"] is True

    # User drops untracked Canvas submissions into submissions/
    sub = proj / "submissions"
    sub.mkdir()
    (sub / "student1.R").write_text("q1 <- 101\n", encoding="utf-8")
    (sub / "student2.R").write_text("q1 <- 202\n", encoding="utf-8")

    effort = proj / "midterm-effort"
    effort.mkdir()

    check_argv = [
        sys.executable,
        "-c",
        "import pathlib; "
        "assert pathlib.Path('submissions/student1.R').read_text().strip() == 'q1 <- 101'; "
        "assert pathlib.Path('submissions/student2.R').read_text().strip() == 'q1 <- 202'; "
        "assert pathlib.Path('similarity_report.md').exists()",
    ]
    writes = {"similarity_report.md": "# Verified 2 submissions\n"}
    started = code_jobs.start(
        str(effort),
        str(proj),
        "Compare submissions/student1.R and student2.R and write similarity_report.md",
        check=check_argv,
        engine_factory=lambda wt: _FakeJobCoder(wt, writes),
    )
    assert started["ok"] is True, f"code_jobs.start failed: {started}"
    jid = started["job"]
    done_job = None
    for _ in range(200):
        j = code_jobs.read_jobs(str(effort)).get(jid) or {}
        if j.get("status") in ("done", "failed", "stopped"):
            done_job = j
            break
        time.sleep(0.05)
    assert done_job is not None and done_job["status"] == "done", f"Job did not finish cleanly: {done_job}"
    assert done_job.get("landed") is True, f"Job did not land: {done_job}"
    assert done_job.get("files") == ["similarity_report.md"]
    assert (proj / "similarity_report.md").exists()
    assert (sub / "student1.R").read_text(encoding="utf-8") == "q1 <- 101\n"
    assert (sub / "student2.R").read_text(encoding="utf-8") == "q1 <- 202\n"


def test_user_profile_personalization_and_new_effort_scaffolding(tmp_path, monkeypatch):
    """Merrill Stat 610 Observations:
    1. When user_profile has display_name='Merrill', Steward prompts address Merrill
       and clarify that role='john' in conversation-log.json is the legacy schema key.
    2. Creating a new effort scaffolds roadmap.json and strip.json so side-panel reads never fail
       on missing files, and personalizes ECGBERHT.md for Merrill."""
    import onboard_wizard
    from steward_cockpit import steward_engine, steward_routes

    merrill_profile = {
        "display_name": "Merrill",
        "pseudonym": "",
        "role": "Collaborator",
        "configured": True,
    }
    monkeypatch.setattr(onboard_wizard, "get_active_user_profile", lambda: merrill_profile)

    sample = "Speak to John in plain English. Wait for John's answer."
    personalized = steward_engine._personalize_prompt_for_user(sample)
    assert "Speak to Merrill in plain English." in personalized
    assert "Wait for Merrill's answer." in personalized
    assert 'legacy schema key role="john"' in personalized

    proj_dir = tmp_path / "Stat 610"
    proj_dir.mkdir()
    res, code = steward_routes._new_effort(str(proj_dir), {"name": "Midterm Shared File Check"})
    assert code == 200 and res["ok"] is True
    effort_dir = proj_dir / res["rel"]
    assert (effort_dir / "roadmap.json").exists()
    assert (effort_dir / "strip.json").exists()
    ecg_md = (effort_dir / "ECGBERHT.md").read_text(encoding="utf-8")
    assert "Merrill" in ecg_md
    assert "John" not in ecg_md
