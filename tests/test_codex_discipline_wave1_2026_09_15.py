"""codex-discipline-2026-09-15 Wave 1 — hermetic contract tests.

Items covered here: 1.4 (delegated preflight applies the parent's bundled
tie-break, trusts a parent-frozen identity honestly, and the failure reason
reaches the session registry) and 1.5 as corrected (sub-agents stay on and
inherit the steward's policy). No real CLI, no network, tmp-rooted registry.
"""
import importlib
import json
from types import SimpleNamespace

import pytest

import codex_adapter as ca
from steward_cockpit.codex_turn_bridge import build_argv


@pytest.fixture(autouse=True)
def fixed_codex_identity_home(tmp_path, monkeypatch):
    profile = tmp_path / "identity-profile"
    codex_home = profile / ".codex"
    codex_home.mkdir(parents=True)
    monkeypatch.setattr(ca, "_os_profile_dir", lambda platform_name=None: profile.resolve())
    monkeypatch.setattr(ca, "_codex_home_path", lambda platform_name=None: codex_home.resolve())
    return codex_home


def _completed(code=0, stdout="", stderr=""):
    return SimpleNamespace(returncode=code, stdout=stdout, stderr=stderr)


def _model(slug, priority, efforts=("high", "ultra")):
    return {"slug": slug, "priority": priority,
            "supported_reasoning_levels": [{"effort": e} for e in efforts]}


TIED_NATIVE = json.dumps({"models": [_model("old-sol", 1), _model("new-astra", 1)]})
BUNDLED = json.dumps({"models": [_model("new-astra", 1), _model("old-sol", 2)]})
UNIQUE_ASTRA = json.dumps({"models": [_model("old-sol", 2), _model("new-astra", 1)]})

PROVENANCE = lambda cmd, _env: {  # noqa: E731 - test shorthand
    "ok": True, "executable_path": cmd,
    "executable_fingerprint": {"path": cmd, "exists": True, "sha256": "d" * 64},
    "executable_provenance_verified": True, "executable_provenance_kind": "test",
}


def _runner(native, bundled=None, bundled_code=0):
    def fake_run(argv, **kwargs):
        if argv[1:] == ["--version"]:
            return _completed(stdout="codex-cli 0.153.4")
        if argv[1:] == ["login", "status"]:
            return _completed(stdout="Logged in using ChatGPT")
        if argv[-3:] == ["debug", "models", "--bundled"]:
            return _completed(code=bundled_code, stdout=bundled or "", stderr="no bundled")
        if argv[-2:] == ["debug", "models"]:
            return _completed(stdout=native)
        raise AssertionError(argv)
    return fake_run


# ── 1.5 (as corrected by John: sub-agents stay on, same policy, attributed) ──

def test_steward_argv_keeps_native_subagents_on_the_steward_policy():
    fresh = build_argv("codex", model="gpt-6-astra", effort="ultra",
                       permission_mode="bypassPermissions")
    resumed = build_argv("codex", model="gpt-6-astra", effort="ultra",
                         permission_mode="bypassPermissions", thread_id="thread-1")
    for argv in (fresh, resumed):
        assert "agents.enabled=false" not in argv and "features.multi_agent=false" not in argv
        assert 'agents.default_subagent_model="gpt-6-astra"' in argv
        assert 'agents.default_subagent_reasoning_effort="ultra"' in argv
        assert argv[-1] == "-"
    assert "resume" in resumed and "thread-1" in resumed


# ── 1.4 preflight ──────────────────────────────────────────────────────────

def test_preflight_resolves_native_tie_with_bundled_priorities(tmp_path):
    result = ca.preflight_codex(
        "C:/fake/codex.exe", env={"CODEX_HOME": str(tmp_path)},
        run_impl=_runner(TIED_NATIVE, BUNDLED), provenance_fn=PROVENANCE)
    assert result["ok"] is True, result
    assert result["selected_model"] == "new-astra"
    assert result["selected_effort"] == "ultra"
    assert result["highest_effort_verified"] is True
    assert "parent_policy_trusted" not in result


def test_preflight_trusts_parent_frozen_policy_on_a_tied_catalog(tmp_path):
    # Unfrozen with the bundled probe unavailable -> the child cannot break the tie.
    without_parent = ca.preflight_codex(
        "C:/fake/codex.exe", env={"CODEX_HOME": str(tmp_path)},
        run_impl=_runner(TIED_NATIVE, bundled_code=1), provenance_fn=PROVENANCE)
    assert without_parent["ok"] is False
    assert without_parent["status"] == "catalog_probe_failed"

    # Frozen -> no second selection and no bundled probe at all; verify and launch.
    calls = []
    inner = _runner(TIED_NATIVE, bundled_code=1)
    def counting(argv, **kw):
        calls.append(argv)
        return inner(argv, **kw)
    frozen = ca.preflight_codex(
        "C:/fake/codex.exe", model="new-astra", effort="ultra",
        env={"CODEX_HOME": str(tmp_path)},
        run_impl=counting, provenance_fn=PROVENANCE)
    assert frozen["ok"] is True, frozen
    assert frozen["selected_model"] == "new-astra"
    assert frozen["parent_policy_trusted"] is True
    assert frozen["model_policy"]["selection_evidence"] == "parent_frozen_policy"
    assert frozen["model_policy"]["model_attested"] is False
    assert frozen["highest_effort_verified"] is True  # ultra is the model's top
    assert frozen["ultra_capability_verified"] is True
    assert not any(argv[-1] == "--bundled" for argv in calls)


def test_preflight_trusts_frozen_identity_when_child_winner_moved(tmp_path):
    # Parent froze old-sol (its 300 s cache); the child sees new-astra unique.
    result = ca.preflight_codex(
        "C:/fake/codex.exe", model="old-sol", effort="ultra",
        env={"CODEX_HOME": str(tmp_path)},
        run_impl=_runner(UNIQUE_ASTRA, UNIQUE_ASTRA), provenance_fn=PROVENANCE)
    assert result["ok"] is True, result
    assert result["selected_model"] == "old-sol"
    assert result["parent_policy_trusted"] is True


def test_preflight_still_refuses_a_frozen_identity_the_catalog_lacks(tmp_path):
    result = ca.preflight_codex(
        "C:/fake/codex.exe", model="retired-model", effort="ultra",
        env={"CODEX_HOME": str(tmp_path)},
        run_impl=_runner(UNIQUE_ASTRA, UNIQUE_ASTRA), provenance_fn=PROVENANCE)
    assert result["ok"] is False
    assert result["status"] == "capability_unavailable"


# ── 1.4 registry ───────────────────────────────────────────────────────────

@pytest.fixture
def reg(tmp_path, monkeypatch):
    monkeypatch.setenv("ANCHOR_DATA_DIR", str(tmp_path))
    import paths
    importlib.reload(paths)
    import session_registry as sr
    importlib.reload(sr)
    return sr


def test_failed_job_reason_reaches_session_registry(reg):
    import job_runner as jr
    rec = reg.register_session("proj-1", "swarm", backend="chatgpt",
                               worktree_path="C:/dev/Some Project")
    sid = rec["session_id"]
    assert reg.get_session(sid)["failure_reason"] == ""

    jr._mirror_session_status(sid, jr.STATUS_FAILED, "catalog_probe_failed")
    after = reg.get_session(sid)
    assert after["status"] == reg.STATUS_FAILED
    assert after["failure_reason"] == "catalog_probe_failed"

    # A successful job mirrors status only and never invents a reason.
    ok = reg.register_session("proj-1", "swarm", backend="chatgpt")
    jr._mirror_session_status(ok["session_id"], jr.STATUS_DONE)
    assert reg.get_session(ok["session_id"])["failure_reason"] == ""

    # Bounded: an oversized reason is cut, never dropped.
    jr._mirror_session_status(sid, jr.STATUS_FAILED, "x" * 500)
    assert len(reg.get_session(sid)["failure_reason"]) == 120
