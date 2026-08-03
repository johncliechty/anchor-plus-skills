"""Locks the PRODUCTION runner-command contract — the real-CLI argv shape.

Root-cause regression guard. The original code emitted ``--skill``,
``--output-dir``, ``--prompt-seed`` (NONE are real ``claude``/``gemini`` flags),
delivered the prompt as DEVNULL stdin (so it never arrived), and used a
read-only approval mode for the research lane (so the report could never be
written). The 209-test baseline only passed because every launch indirected
through ``ANCHOR_RUNNER_CMD`` → the mock, which tolerates unknown args — so the
real-CLI path was NEVER exercised.

These tests pin the argv that ``job_runner`` builds when ``ANCHOR_RUNNER_CMD`` is
UNSET (production), per backend and per lane:
- the right binary (claude / gemini),
- the natural-language prompt delivered correctly (argv for research; stdin for
  gated lanes — verified by the launch wiring),
- the project-scoped output dir passed via the REAL flag (--add-dir /
  --include-directories),
- a WRITE-capable permission/approval mode,
- and NONE of the dead flags (--skill / --output-dir / --prompt-seed).

NO live CLI is invoked: these inspect the constructed argv directly (no Popen).
"""
import importlib
import os

import pytest

DEAD_FLAGS = ("--skill", "--output-dir", "--prompt-seed")


@pytest.fixture
def jr(tmp_path, monkeypatch):
    monkeypatch.setenv("ANCHOR_DATA_DIR", str(tmp_path))
    # CRITICAL: unset the test indirection so the REAL-CLI argv builder runs.
    monkeypatch.delenv("ANCHOR_RUNNER_CMD", raising=False)
    monkeypatch.delenv("ANCHOR_GEMINI_CMD", raising=False)
    import paths
    importlib.reload(paths)
    import job_runner
    importlib.reload(job_runner)
    return job_runner


SEED = "Run the researchPrime skill for project 'X'. Write under /out."
OUT = "/proj/.anchor/projects/abc/research"


# ── claude RESEARCH (non-gated) ───────────────────────────────────────────────

def test_claude_research_argv_is_valid_and_has_no_dead_flags(jr):
    argv = jr.resolve_runner_cmd(backend="claude", prompt=SEED,
                                 output_dir=OUT, gated=False)
    assert argv[0] == "claude"
    assert "-p" in argv
    assert "--output-format" in argv and "stream-json" in argv
    # Live-CLI requirement: --print + stream-json REQUIRES --verbose.
    assert "--verbose" in argv
    # Output dir via the REAL flag, not --output-dir.
    assert "--add-dir" in argv
    assert OUT in argv
    # WRITE-capable permission mode (research must write its report).
    i = argv.index("--permission-mode")
    assert argv[i + 1] == "acceptEdits"
    # The natural-language seed IS the prompt, on argv (non-gated).
    assert SEED in argv
    # NONE of the dead flags survive.
    for dead in DEAD_FLAGS:
        assert dead not in argv
    # Research is non-gated → NO stdin input-format (prompt is on argv).
    assert "--input-format" not in argv


# ── claude PLAN (gated, non-mutating) ─────────────────────────────────────────

def test_claude_plan_argv_gated_stdin_acceptedits(jr):
    argv = jr.resolve_runner_cmd(backend="claude", prompt=SEED,
                                 output_dir=OUT, gated="plan")
    assert argv[0] == "claude"
    # Gated → prompt arrives on stdin → --input-format stream-json present.
    assert "--input-format" in argv
    assert "--add-dir" in argv and OUT in argv
    i = argv.index("--permission-mode")
    assert argv[i + 1] == "acceptEdits"   # plan writes docs, non-mutating
    # Gated lanes must NOT carry the prompt on argv (it goes on stdin).
    assert SEED not in argv
    for dead in DEAD_FLAGS:
        assert dead not in argv


# ── claude BUILD (gated, mutating) ────────────────────────────────────────────

def test_claude_build_argv_gated_bypass_permissions(jr):
    argv = jr.resolve_runner_cmd(backend="claude", prompt=SEED,
                                 output_dir=OUT, gated="build")
    assert argv[0] == "claude"
    assert "--input-format" in argv
    i = argv.index("--permission-mode")
    # build mutates the tree + may run Bash → bypassPermissions.
    assert argv[i + 1] == "bypassPermissions"
    assert SEED not in argv
    for dead in DEAD_FLAGS:
        assert dead not in argv


# ── gemini RESEARCH (research-only) ───────────────────────────────────────────

def test_gemini_research_argv_is_valid_and_has_no_dead_flags(jr):
    # This host has NO bare `gemini` binary — a real Gemini launch routes through
    # the thin Node adapter `agy_job_adapter.mjs`, which drives the sanctioned
    # `agy-dispatch` transport and re-emits one stream-json `result` line. The old
    # `gemini --skip-trust -p … --output-format stream-json --approval-mode …`
    # CLI flags are DEAD (they hard-error on the agy CLI).
    argv = jr.resolve_runner_cmd(backend="gemini", prompt=SEED,
                                 output_dir=OUT, gated=False)
    assert argv[0] == "node"
    # The adapter is the script argument.
    assert argv[1].endswith("agy_job_adapter.mjs")
    # The (possibly large) prompt is delivered via a temp FILE, never on argv
    # (agy's argv ceiling is ~32KB) — so the seed must NOT leak into argv.
    assert "--prompt-file" in argv
    assert SEED not in argv
    prompt_file = argv[argv.index("--prompt-file") + 1]
    assert prompt_file and prompt_file != SEED
    # The model is passed explicitly.
    assert "--model" in argv and argv[argv.index("--model") + 1]
    # Output dir via the adapter's --target (NOT the dead --output-dir).
    assert "--target" in argv
    assert argv[argv.index("--target") + 1] == OUT
    # WRITE-capable posture: research writes its report, so the read-only
    # `--readonly` flag must NOT be present on a non-gated research launch.
    assert "--readonly" not in argv
    # NONE of the retired gemini CLI flags survive.
    for dead in DEAD_FLAGS + ("--skip-trust", "-p", "--output-format",
                              "--approval-mode", "--include-directories"):
        assert dead not in argv


# ── override path still wins + appends prompt the mock tolerates ──────────────

def test_override_wins_and_appends_prompt_as_trailing_arg(jr, monkeypatch):
    monkeypatch.setenv("ANCHOR_RUNNER_CMD", "python /tmp/fake_claude.py")
    argv = jr.resolve_runner_cmd(backend="claude", prompt=SEED,
                                 output_dir=OUT, gated="build",
                                 extra_args=["--lines", "2"])
    # The override base is used verbatim — NOT the real claude/gemini builder.
    assert argv[0] == "python"
    assert "/tmp/fake_claude.py" in argv
    assert "claude" != argv[0] and "gemini" != argv[0]
    # The prompt is appended as a trailing arg the mock ignores (parse_known).
    assert SEED in argv
    # Test flags come last.
    assert argv[-2:] == ["--lines", "2"]
    # Real flags are NOT injected on the override path.
    for dead in DEAD_FLAGS + ("--add-dir", "--include-directories",
                              "--permission-mode"):
        assert dead not in argv


def test_shape_only_resolution_unchanged_when_no_prompt(jr):
    # No prompt → shape-only base (the engine-selector contract).
    claude = jr.resolve_runner_cmd(backend="claude")
    assert claude[0] == "claude" and "-p" in claude
    gemini = jr.resolve_runner_cmd(backend="gemini")
    assert gemini[0] == "gemini" and "--skip-trust" in gemini
    assert "--approval-mode" in gemini


# ── Gandalf read-only contract (permission_mode override) ─────────────────────
# Gandalf is an ADVISOR: it analyzes a project and emits its read as the final
# message; it writes NO file, so it must run claude READ-ONLY (plan), never
# acceptEdits — otherwise an analysis could edit the user's real repo. These pin
# the permission_mode threading + that Gandalf's Stage A uses it.

def test_research_default_permission_is_accept_edits(jr):
    """Default (no override) research argv keeps the write-capable acceptEdits."""
    argv = jr.build_backend_argv("claude", SEED, OUT, False)
    i = argv.index("--permission-mode")
    assert argv[i + 1] == "acceptEdits"


def test_permission_mode_plan_is_read_only(jr):
    """permission_mode='plan' → read-only argv (no acceptEdits anywhere)."""
    argv = jr.build_backend_argv("claude", SEED, OUT, False, permission_mode="plan")
    i = argv.index("--permission-mode")
    assert argv[i + 1] == "plan"
    assert "acceptEdits" not in argv


def test_resolve_runner_cmd_threads_permission_mode(jr):
    """resolve_runner_cmd forwards permission_mode to the builder on the real path."""
    argv = jr.resolve_runner_cmd(backend="claude", prompt=SEED, output_dir=OUT,
                                 gated=False, permission_mode="plan")
    assert "plan" in argv and "acceptEdits" not in argv


def test_gandalf_stage_a_launches_read_only(jr, monkeypatch):
    """Gandalf's Stage A MUST launch claude with permission_mode='plan' (read-only)."""
    import importlib
    import gandalf
    importlib.reload(gandalf)
    captured = {}

    def fake_launch(*a, **k):
        captured.update(k)
        raise RuntimeError("stop-after-capture")

    monkeypatch.setattr(gandalf._jr, "launch", fake_launch)
    gandalf._run_stage_a("/some/project")  # swallows the error → (None, "launch-failed")
    assert captured.get("permission_mode") == "plan", \
        "Gandalf Stage A must run read-only (plan), never acceptEdits"
