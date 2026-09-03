"""Hermetic contract tests for Anchor's ChatGPT subscription adapter."""

import json
import io
import os
import subprocess
import sys
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest

import codex_adapter as ca


@pytest.fixture(autouse=True)
def fixed_codex_identity_home(tmp_path, monkeypatch):
    profile = tmp_path / "identity-profile"
    codex_home = profile / ".codex"
    codex_home.mkdir(parents=True)
    monkeypatch.setattr(
        ca, "_os_profile_dir", lambda platform_name=None: profile.resolve())
    monkeypatch.setattr(
        ca, "_codex_home_path", lambda platform_name=None: codex_home.resolve())
    return codex_home


def _completed(code=0, stdout="", stderr=""):
    return SimpleNamespace(returncode=code, stdout=stdout, stderr=stderr)


def _catalog(efforts=("max", "ultra")):
    return json.dumps({
        "models": [{
            "slug": ca.CODEX_MODEL,
            "supported_reasoning_levels": [{"effort": effort} for effort in efforts],
        }],
    })


def _ready(executable="C:/trusted/codex.exe", **overrides):
    result = {
        "ok": True,
        "status": "ready",
        "executable_path": executable,
        "transport_actual": "codex-cli",
        "cli_version": "codex-cli test",
        "auth_kind": "chatgpt_subscription",
        "auth_probe_at": "2026-08-30T15:00:00+00:00",
        "subscription_auth": True,
        "model_capability_verified": True,
        "ultra_capability_verified": True,
        "config_guard_verified": True,
        "runtime_guard_rechecked": False,
        "config_fingerprint": {
            "path": "config.toml", "exists": False, "sha256": None,
        },
        "executable_fingerprint": {
            "path": executable, "exists": True, "sha256": "a" * 64,
            "size": 10, "mtime_ns": 1, "device": 1, "inode": 1,
        },
        "executable_provenance_verified": True,
        "signer_image_binding_verified": True,
        "executable_provenance_kind": "test-attestation",
        "child_env_allowlist_verified": True,
        "api_key_env_scrubbed": True,
        "mcp_entries_absent": True,
    }
    result.update(overrides)
    return result


class _FakeWindowsJob:
    policy_verified = True

    def __init__(self):
        self.assigned = False
        self.membership_verified = False
        self.process_handle_verified = False
        self.primary_thread_verified = False
        self.resumed = False
        self.execution_possible = False
        self.empty_verified = False
        self.closed = False

    def assign_and_resume(self, _proc, cancel_before_resume=False):
        self.process_handle_verified = True
        self.assigned = True
        self.membership_verified = True
        self.primary_thread_verified = True
        cancelled = (bool(cancel_before_resume())
                     if callable(cancel_before_resume)
                     else bool(cancel_before_resume))
        if cancelled:
            return False
        self.execution_possible = True
        self.resumed = True
        return True

    def terminate_verified(self, _proc, timeout_seconds=5.0):
        self.empty_verified = True
        return True

    def abort_suspended(self, _proc):
        self.empty_verified = True
        return True

    def verify_empty(self):
        self.empty_verified = True
        return True

    def close(self):
        self.closed = True


def _run_codex(*args, **kwargs):
    kwargs.setdefault("resolve_fn", lambda _env: "C:/trusted/codex.exe")
    kwargs.setdefault("guard_recheck_fn", lambda *_args: {
        "ok": True, "config_guard_verified": True,
        "runtime_guard_rechecked": True,
        "executable_provenance_verified": True,
        "signer_image_binding_verified": True,
        "user_config_ignored": True,
        "mcp_entries_absent": True,
        "executable_handle_guarded_through_spawn": False,
        "preexecution_child_image_attested": False,
    })
    kwargs.setdefault("windows_job_factory", _FakeWindowsJob)
    return ca.run_codex(*args, **kwargs)


def test_overflow_cleanup_uses_platform_appropriate_proof(monkeypatch):
    proc = SimpleNamespace()
    monkeypatch.setattr(ca, "_proc_dead", lambda *_args, **_kwargs: True)
    assert ca._overflow_cleanup_verified(proc, "nt", True, True, None) is True
    assert ca._overflow_cleanup_verified(proc, "nt", True, False, None) is False
    assert ca._overflow_cleanup_verified(
        proc, "nt", True, False, None,
        complete_tree_containment=True,
        windows_job_empty_verified=True) is True
    assert ca._overflow_cleanup_verified(
        proc, "posix", True, False, True) is True
    assert ca._overflow_cleanup_verified(
        proc, "posix", True, False, False) is False
    assert ca._overflow_cleanup_verified(
        proc, "posix", False, False, True) is False


def test_exec_argv_is_isolated_safe_and_prompt_on_stdin(tmp_path):
    target = tmp_path / 'dotted.path spaces 雪'
    target.mkdir()
    argv = ca.build_exec_argv("codex.exe", target, sandbox="read-only")
    assert argv[0:3] == ["codex.exe", "exec", "--skip-git-repo-check"]
    for flag in ("--ephemeral", "--ignore-rules", "--strict-config", "--json"):
        assert flag in argv
    assert "--ignore-user-config" in argv
    assert argv[-1] == "-"
    assert argv[argv.index("--sandbox") + 1] == "read-only"
    assert argv[argv.index("--model") + 1] == ca.CODEX_MODEL
    assert 'model_reasoning_effort="ultra"' in argv
    assert 'approval_policy="never"' in argv
    assert 'model_provider="openai"' in argv
    assert "agents.enabled=false" in argv
    for override in (
        "features.multi_agent=false",
        "model_providers={}",
        "mcp_servers={}",
        "apps={}",
        "features.apps=false",
        "apps._default.enabled=false",
        "features.hooks=false",
        "features.skill_mcp_dependency_install=false",
        "features.remote_plugin=false",
        "features.plugins=false",
        "features.browser_use=false",
        "features.browser_use_external=false",
        "features.computer_use=false",
        "features.image_generation=false",
        'web_search="disabled"',
        "tools.web_search=false",
        "sandbox_workspace_write.network_access=false",
        "sandbox_workspace_write.writable_roots=[]",
        "sandbox_workspace_write.exclude_slash_tmp=true",
        "sandbox_workspace_write.exclude_tmpdir_env_var=true",
        'shell_environment_policy.inherit="core"',
        "shell_environment_policy.ignore_default_excludes=false",
        "shell_environment_policy.set={}",
    ):
        assert override in argv
    projects = next(value for value in argv if value.startswith("projects={"))
    assert str(target.resolve()) in json.loads(
        projects[len("projects={"):].split("={trust_level", 1)[0])
    assert ".trust_level=" not in projects
    assert ca._toml_basic_string('quote" and 雪') == '"quote\\" and 雪"'
    assert "secret prompt" not in argv
    with pytest.raises(ValueError, match="MCP"):
        ca.build_exec_argv(
            "codex.exe", target, mcp_server_ids=("even-one",))
    with pytest.raises(ValueError, match="sandbox"):
        ca.build_exec_argv("codex.exe", tmp_path, sandbox="danger-full-access")


def test_subscription_environment_scrubs_api_auth_and_keeps_saved_login_context():
    hostile_os_values = {
        "COMSPEC": "C:/attacker/cmd.exe",
        "PATHEXT": ".EVIL",
        "APPDATA": "C:/attacker/roaming",
        "LOCALAPPDATA": "C:/attacker/local",
        "HOME": "C:/attacker/home",
        "TEMP": "C:/attacker/temp",
        "TMP": "C:/attacker/tmp",
        "TMPDIR": "C:/attacker/tmpdir",
        "XDG_CONFIG_HOME": "C:/attacker/xdg",
    }
    clean = ca.subscription_only_env({
        "PATH": "ok",
        "CODEX_HOME": "saved-login",
        "codex_home": "case-conflict-must-not-survive",
        "OPENAI_API_KEY": "secret",
        "CODEX_API_KEY": "secret2",
        "CODEX_ACCESS_TOKEN": "secret3",
        "OPENAI_BASE_URL": "https://example.invalid",
        "OpenAi_Api_Key": "mixed-case-secret",
        "anchor_codex_cmd": "C:/malicious/codex.exe",
        "CoDeX_BiN": "C:/also-malicious/codex.exe",
        "AWS_WEB_IDENTITY_TOKEN_FILE": "secret-token-file",
        "AZURE_FEDERATED_TOKEN_FILE": "secret-token-file-2",
        "GOOGLE_APPLICATION_CREDENTIALS": "secret-token-file-3",
        "GITHUB_TOKEN": "secret4",
        "OIDC_TOKEN": "secret5",
        "OPENAI_REFRESH_TOKEN": "secret6",
        "SOME_PROVIDER_ENDPOINT": "https://attacker.invalid",
        **hostile_os_values,
    })
    assert clean["PATH"] != "ok"
    assert "malicious" not in clean["PATH"].casefold()
    assert Path(clean["CODEX_HOME"]).is_absolute()
    assert clean["CODEX_HOME"] != "saved-login"
    assert "codex_home" not in clean
    for key in ca.API_AUTH_ENV_KEYS:
        assert key not in clean
    assert all(key.upper() not in (
        ca.API_AUTH_ENV_KEYS | ca.COMMAND_OVERRIDE_ENV_KEYS) for key in clean)
    assert "CI" not in clean and clean["NO_COLOR"] == "1"
    assert all("TOKEN" not in key and "CREDENTIAL" not in key
               and "PROVIDER" not in key for key in clean)
    assert ca._minimal_env_verified(clean) is True
    assert "XDG_CONFIG_HOME" not in clean
    for key, hostile in hostile_os_values.items():
        if key in clean:
            assert clean[key] != hostile
    widened = dict(clean, UNDOCUMENTED_RUNTIME="1")
    assert ca._minimal_env_verified(widened) is False


def test_command_override_is_ignored_by_trusted_executable_resolution(
        tmp_path, monkeypatch):
    trusted = tmp_path / "approved" / "bin"
    trusted.mkdir(parents=True)
    executable = trusted / ("codex.exe" if ca.os.name == "nt" else "codex")
    executable.write_text("trusted", encoding="utf-8")
    monkeypatch.setattr(
        ca, "_known_codex_roots",
        lambda env=None, platform_name=None: [trusted.resolve()])
    resolved = ca.resolve_codex_cmd({
        "LOCALAPPDATA": str(tmp_path),
        "ANCHOR_CODEX_CMD": "C:/malicious/codex.exe",
        "CODEX_BIN": "C:/malicious/also.exe",
    })
    assert resolved == str(executable.resolve())


def test_executable_resolution_never_falls_back_to_caller_path(monkeypatch):
    monkeypatch.setattr(ca, "_known_codex_roots", lambda *_args: [])
    with pytest.raises(FileNotFoundError, match="approved installation"):
        ca.resolve_codex_cmd({
            "PATH": "C:/malicious/bin",
            "ANCHOR_CODEX_CMD": "C:/malicious/codex.exe",
        })


def test_config_guard_refuses_provider_override_and_all_mcp_entries(
        fixed_codex_identity_home):
    codex_home = fixed_codex_identity_home
    config = codex_home / "config.toml"
    config.write_text(
        '[model_providers.evil]\nname = "forged"\nbase_url = "https://invalid"\n',
        encoding="utf-8",
    )
    refused = ca.inspect_user_config({"CODEX_HOME": str(codex_home)})
    assert refused["ok"] is False
    assert refused["status"] == "config_guard_failed"
    assert "model_providers" in refused["error"]

    config.write_text('[mcp_servers.""]\ncommand = "even-empty-is-code"\n',
                      encoding="utf-8")
    forbidden = ca.inspect_user_config({"CODEX_HOME": "C:/ignored"})
    assert forbidden["ok"] is False
    assert "MCP" in forbidden["error"] and "''" in forbidden["error"]

    config.write_text('mcp_servers = ["not-a-table"]\n', encoding="utf-8")
    malformed = ca.inspect_user_config({"CODEX_HOME": str(codex_home)})
    assert malformed["ok"] is False
    assert "not a table" in malformed["error"]

    config.write_text('model = "harmless"\n', encoding="utf-8")
    guarded = ca.inspect_user_config({"CODEX_HOME": "C:/redirect-ignored"})
    assert guarded["ok"] is True
    assert guarded["codex_home"] == str(codex_home.resolve())
    assert guarded["config_fingerprint"]["sha256"]


@pytest.mark.parametrize("body,needle", [
    ('notify = ["evil.exe"]\n', "notify"),
    ('[hooks]\nafter = "evil.exe"\n', "hooks"),
    ('[apps]\nenabled = true\n', "apps"),
    ('[plugins]\npath = "evil"\n', "plugins"),
    ('model_provider = "evil"\n', "model_provider"),
    ('openai_base_url = "https://evil.invalid"\n', "openai_base_url"),
    ('profile = "evil"\n[profiles.evil]\nmodel_provider = "evil"\n', "profile"),
    ('[features]\napps = true\n', "apps"),
])
def test_config_guard_refuses_every_executable_or_provider_widening_key(
        fixed_codex_identity_home, body, needle):
    (fixed_codex_identity_home / "config.toml").write_text(body, encoding="utf-8")
    result = ca.inspect_user_config({})
    assert result["ok"] is False
    assert needle in result["error"]


def test_user_config_replacement_after_recheck_is_excluded_from_child(
        tmp_path, fixed_codex_identity_home):
    observed = {}

    class Proc:
        pid = 811
        returncode = 0

        def communicate(self, input=None, timeout=None):
            return _success_stream("CONFIG_IGNORED"), ""

    def popen(argv, **_kwargs):
        (fixed_codex_identity_home / "config.toml").write_text(
            'notify = ["evil.exe"]\n[mcp_servers.evil]\ncommand="evil"\n',
            encoding="utf-8")
        observed["argv"] = list(argv)
        return Proc()

    envelope, code, _out, _err = _run_codex(
        "work", tmp_path, preflight_fn=lambda *_args: _ready(),
        popen_impl=popen,
    )
    assert code == 0 and envelope["result"] == "CONFIG_IGNORED"
    assert "--ignore-user-config" in observed["argv"]
    receipt = envelope["model_receipt"]
    assert receipt["user_config_loaded"] is False
    assert receipt["user_config_ignored"] is True


def test_runtime_guard_rejects_executable_hash_change(
        tmp_path, fixed_codex_identity_home, monkeypatch):
    trusted = tmp_path / "approved"
    trusted.mkdir()
    executable = trusted / "codex.exe"
    executable.write_bytes(b"first-image")
    executable.chmod(0o700)
    monkeypatch.setattr(ca, "_known_codex_roots", lambda *_args: [trusted.resolve()])
    monkeypatch.setattr(ca, "_windows_authenticode", lambda *_args, **_kwargs: {
        "ok": True, "signer_subject": "CN/O exact",
    })
    config = ca.inspect_user_config({})
    first = ca.inspect_executable(str(executable.resolve()), {}, "nt")
    assert first["ok"] is True
    preflight = _ready(
        executable=str(executable.resolve()), codex_home=config["codex_home"],
        config_fingerprint=config["config_fingerprint"],
        executable_fingerprint=first["executable_fingerprint"],
    )
    executable.write_bytes(b"second-image")
    result = ca.recheck_runtime_guard(preflight, {}, "nt")
    assert result["ok"] is False
    assert result["status"] == "executable_guard_changed"


def test_windows_authenticode_requires_winverifytrust_and_exact_cn_o(
        tmp_path):
    executable = tmp_path / "codex.exe"
    executable.write_bytes(b"signed-image")

    def trust(cn="OpenAI OpCo, LLC", org="OpenAI OpCo, LLC", ok=True):
        return lambda *_args, **_kwargs: {
            "ok": ok, "signature_status": "0x00000000" if ok else "0x800b0100",
            "signer_common_name": cn, "signer_organization": org,
            "signer_certificate_sha256": "c" * 64,
        }

    exact = ca._windows_authenticode(
        executable, {"SYSTEMROOT": str(tmp_path)},
        run_impl=lambda *_args, **_kwargs: pytest.fail(
            "signer must come from WinVerifyTrust provider state"),
        trust_impl=trust(),
        windows_dir_fn=lambda: tmp_path,
    )
    assert exact["ok"] is True
    assert exact["signer_certificate_sha256"] == "c" * 64
    wrong_org = ca._windows_authenticode(
        executable, {"SYSTEMROOT": str(tmp_path)},
        trust_impl=trust(org="Lookalike OpenAI"),
        windows_dir_fn=lambda: tmp_path,
    )
    assert wrong_org["ok"] is False
    trust_rejected = ca._windows_authenticode(
        executable, {"SYSTEMROOT": str(tmp_path)},
        run_impl=lambda *_args, **_kwargs: pytest.fail("must not query signer"),
        trust_impl=trust(ok=False),
        windows_dir_fn=lambda: tmp_path,
    )
    assert trust_rejected["ok"] is False
    assert "WinVerifyTrust" in trust_rejected["error"]


def test_executable_provenance_requires_canonical_known_root_and_signature(
        tmp_path, monkeypatch):
    trusted = tmp_path / "approved"
    trusted.mkdir()
    executable = trusted / "codex.exe"
    executable.write_bytes(b"candidate")
    outside = tmp_path / "codex.exe"
    outside.write_bytes(b"outside")
    monkeypatch.setattr(ca, "_known_codex_roots", lambda *_args: [trusted.resolve()])
    monkeypatch.setattr(ca, "_windows_authenticode", lambda *_args, **_kwargs: {
        "ok": True, "signer_subject": "CN/O exact",
    })
    accepted = ca.inspect_executable(str(executable.resolve()), {}, "nt")
    assert accepted["ok"] is True
    assert accepted["executable_fingerprint"]["sha256"] == \
        ca.hashlib.sha256(b"candidate").hexdigest()
    refused = ca.inspect_executable(str(outside.resolve()), {}, "nt")
    assert refused["ok"] is False
    assert "approved" in refused["error"]


@pytest.mark.skipif(os.name != "nt", reason="Windows file sharing is required")
def test_windows_provenance_guard_blocks_image_replacement_during_signer_probe(
        tmp_path, monkeypatch):
    trusted = tmp_path / "approved"
    trusted.mkdir()
    executable = trusted / "codex.exe"
    original = b"guarded-openai-image"
    executable.write_bytes(original)
    monkeypatch.setattr(ca, "_known_codex_roots", lambda *_args: [trusted.resolve()])
    observed = {"blocked": False}

    def signer_while_guarded(path, *_args, **kwargs):
        guarded_handle = kwargs.get("guarded_handle")
        assert guarded_handle is not None
        assert guarded_handle.closed is False
        try:
            path.write_bytes(b"replacement")
        except OSError:
            observed["blocked"] = True
        return {
            "ok": True,
            "signer_subject": 'CN="OpenAI OpCo, LLC", O="OpenAI OpCo, LLC"',
            "signature_revocation_freshness": "unproven_cache_only",
        }

    monkeypatch.setattr(ca, "_windows_authenticode", signer_while_guarded)
    attested = ca.inspect_executable(str(executable), {}, "nt")
    assert attested["ok"] is True
    assert observed["blocked"] is True
    assert attested["signer_image_binding_verified"] is True
    assert attested["executable_fingerprint"]["sha256"] == \
        ca.hashlib.sha256(original).hexdigest()
    assert executable.read_bytes() == original


@pytest.mark.skipif(os.name != "nt", reason="Windows Authenticode provider state")
def test_installed_codex_wvt_provider_state_binds_exact_openai_leaf_offline():
    try:
        executable = Path(ca.resolve_codex_cmd({})).resolve()
    except FileNotFoundError:
        pytest.skip("installed Codex binary is unavailable")
    with ca._open_guarded_file(executable) as guard:
        evidence = ca._win_verify_trust(executable, guard)
    assert evidence["ok"] is True, evidence
    assert evidence["signature_status"] == "0x00000000"
    assert evidence["signer_common_name"] == "OpenAI OpCo, LLC"
    assert evidence["signer_organization"] == "OpenAI OpCo, LLC"
    assert len(evidence["signer_certificate_sha256"]) == 64


def test_preflight_attests_subscription_and_installed_ultra_without_shell(tmp_path):
    calls = []

    def fake_run(argv, **kwargs):
        calls.append((argv, kwargs))
        if argv[1:] == ["--version"]:
            return _completed(stdout="codex-cli 0.151.0")
        if argv[1:] == ["login", "status"]:
            return _completed(stdout="Logged in using ChatGPT")
        if argv[-2:] == ["debug", "models"]:
            return _completed(stdout=_catalog())
        raise AssertionError(argv)

    result = ca.preflight_codex(
        "C:/fake/codex.exe", env={
            "OPENAI_API_KEY": "must-go", "CODEX_HOME": str(tmp_path),
        },
        run_impl=fake_run, now_fn=lambda: "2026-08-30T15:00:00+00:00",
        provenance_fn=lambda cmd, _env: {
            "ok": True, "executable_path": cmd,
            "executable_fingerprint": {
                "path": cmd, "exists": True, "sha256": "b" * 64,
            },
            "executable_provenance_verified": True,
            "executable_provenance_kind": "test",
        },
    )
    assert result["ok"] is True
    assert result["auth_kind"] == "chatgpt_subscription"
    assert result["subscription_auth"] is True
    assert result["model_capability_verified"] is True
    assert result["ultra_capability_verified"] is True
    assert result["cli_version"] == "codex-cli 0.151.0"
    assert result["transport_actual"] == "codex-cli"
    # Preflight verifies the saved subscription and executable only.  The
    # immutable config boundary is established by --ignore-user-config on the
    # actual execution argv and is therefore not claimed before a seat exists.
    assert result["config_guard_verified"] is False
    assert result["user_config_ignored"] is False
    assert result["executable_provenance_verified"] is True
    assert result["child_env_allowlist_verified"] is True
    assert len(calls) == 3
    for argv, kwargs in calls:
        assert kwargs["shell"] is False
        assert "OPENAI_API_KEY" not in kwargs["env"]
        assert Path(argv[0]).is_absolute()
        assert kwargs["executable"] == argv[0]
        assert Path(kwargs["cwd"]) == Path(argv[0]).parent


def test_preflight_distinguishes_auth_catalog_and_capability_failures(tmp_path):
    clean_env = {"CODEX_HOME": str(tmp_path)}

    def api_login(argv, **_kwargs):
        if argv[1:] == ["--version"]:
            return _completed(stdout="codex-cli test")
        return _completed(stdout="Logged in using an API key")

    provenance = lambda cmd, _env: {
        "ok": True, "executable_path": cmd,
        "executable_fingerprint": {"path": cmd, "exists": True, "sha256": "c" * 64},
        "executable_provenance_verified": True,
    }
    auth = ca.preflight_codex(
        "codex", env=clean_env, run_impl=api_login,
        provenance_fn=provenance)
    assert auth["status"] == "subscription_auth_required"
    assert auth["subscription_auth"] is False

    def broken_catalog(argv, **_kwargs):
        if argv[1:] == ["--version"]:
            return _completed(stdout="codex-cli test")
        if argv[1:] == ["login", "status"]:
            return _completed(stdout="Logged in using ChatGPT")
        return _completed(code=1, stderr="catalog command crashed")

    broken = ca.preflight_codex(
        "codex", env=clean_env, run_impl=broken_catalog,
        provenance_fn=provenance)
    assert broken["status"] == "catalog_probe_failed"
    assert broken["subscription_auth"] is True

    def no_ultra(argv, **_kwargs):
        if argv[1:] == ["--version"]:
            return _completed(stdout="codex-cli test")
        if argv[1:] == ["login", "status"]:
            return _completed(stdout="Logged in using ChatGPT")
        return _completed(stdout=_catalog(("max",)))

    missing = ca.preflight_codex(
        "codex", env=clean_env, run_impl=no_ultra,
        provenance_fn=provenance)
    assert missing["status"] == "capability_unavailable"
    assert missing["model_capability_verified"] is True
    assert missing["ultra_capability_verified"] is False


def test_jsonl_parser_keeps_answer_usage_and_structured_failure_boundaries():
    stream = "\n".join((
        json.dumps({"type": "thread.started", "thread_id": "thread-1"}),
        json.dumps({"type": "item.completed", "item": {
            "type": "agent_message", "text": "There were 429 records; all are valid.",
        }}),
        json.dumps({"type": "turn.completed", "usage": {
            "input_tokens": 429, "cached_input_tokens": 300, "output_tokens": 7,
        }}),
    ))
    parsed = ca.parse_jsonl(stream)
    assert parsed["ok"] is True
    assert parsed["text"].startswith("There were 429")
    assert parsed["thread_id"] == "thread-1"
    assert parsed["usage"]["input_tokens"] == 429
    assert ca.classify_failure("", parsed, 0) == "success"

    with_banner = ca.parse_jsonl("codex informational banner\n" + stream)
    assert with_banner["ok"] is True
    assert with_banner["malformed_count"] == 1

    failed = ca.parse_jsonl(json.dumps({
        "type": "turn.failed", "error": {"code": "rate_limit", "message": "429 quota"},
    }))
    assert ca.classify_failure("", failed, 0) == "usage_limit"


@pytest.mark.parametrize("bad_value", [-1, ca.MAX_NATIVE_TOKEN_COUNT + 1, 1.5, "7", True])
def test_jsonl_parser_rejects_negative_unbounded_or_noninteger_native_usage(
        bad_value):
    stream = "\n".join((
        json.dumps({"type": "item.completed", "item": {
            "type": "agent_message", "text": "must not become success",
        }}),
        json.dumps({"type": "turn.completed", "usage": {
            "input_tokens": bad_value,
        }}),
    ))
    parsed = ca.parse_jsonl(stream)
    assert parsed["ok"] is False
    assert parsed["usage_valid"] is False
    assert parsed["usage"]["input_tokens"] == 0
    assert ca.classify_failure("", parsed, 0) == "protocol_error"


def test_run_codex_forwards_prompt_only_on_stdin_and_emits_honest_receipt(tmp_path):
    prompt = "Return the bounded sentinel."
    observed = {}
    (tmp_path / "codex.dll").write_bytes(b"project-cwd-search-order-trap")

    def fake_preflight(cmd, model, effort, env):
        observed["preflight"] = (cmd, model, effort, env)
        return _ready(executable=cmd)

    class FakeProc:
        pid = 123
        returncode = 0

        def communicate(self, input=None, timeout=None):
            observed["input"] = input
            observed["timeout"] = timeout
            return "\n".join((
                json.dumps({"type": "thread.started", "thread_id": "t-live"}),
                json.dumps({"type": "item.completed", "item": {
                    "type": "agent_message", "text": "ADAPTER_OK",
                }}),
                json.dumps({"type": "turn.completed", "usage": {
                    "input_tokens": 12, "cached_input_tokens": 4, "output_tokens": 2,
                }}),
            )), ""

    def fake_popen(argv, **kwargs):
        observed["argv"] = argv
        observed["popen"] = kwargs
        return FakeProc()

    envelope, code, native_out, native_err = _run_codex(
        prompt,
        tmp_path,
        sandbox="read-only",
        timeout_seconds=30,
        env={
            "ANCHOR_CODEX_CMD": "C:/fake/codex.exe",
            "OPENAI_API_KEY": "must-not-reach-child",
        },
        preflight_fn=fake_preflight,
        popen_impl=fake_popen,
    )
    assert code == 0 and native_out and native_err == ""
    assert observed["input"] == prompt
    assert prompt not in observed["argv"]
    assert observed["argv"][-1] == "-"
    assert observed["popen"]["shell"] is False
    assert Path(observed["popen"]["cwd"]) == Path(
        observed["popen"]["executable"]).parent
    assert Path(observed["popen"]["cwd"]) != tmp_path
    assert observed["argv"][observed["argv"].index("--cd") + 1] == \
        str(tmp_path.resolve())
    assert "OPENAI_API_KEY" not in observed["popen"]["env"]
    assert observed["preflight"][0] != "C:/fake/codex.exe"
    assert envelope["type"] == "result"
    assert envelope["result"] == "ADAPTER_OK"
    receipt = envelope["model_receipt"]
    assert receipt["requested_model"] == ca.CODEX_MODEL
    assert receipt["requested_effort"] == "ultra"
    assert receipt["model_served"] is None
    assert receipt["model_attested"] is False
    assert receipt["degraded"] is True
    assert receipt["billing_mode"] == "subscription"
    assert receipt["cost_state"] == "subscription_covered"
    assert receipt["seat_started"] is True
    assert receipt["model_provider_requested"] == "openai"
    assert receipt["user_config_loaded"] is False
    assert receipt["critical_overrides_enforced"] is True
    assert receipt["rules_ignored"] is True
    assert receipt["agents_disabled"] is True
    assert receipt["artifact_write_observed"] is False
    assert receipt["artifact_paths"] == []
    assert receipt["artifact_mutation_verified"] is False
    assert receipt["artifact_contract_verified"] is False
    assert receipt["artifact_contract_verified"] == \
        receipt["artifact_mutation_verified"]
    assert receipt["tree_kill_verified"] is None
    assert receipt["prompt_sha256"] and prompt not in json.dumps(receipt)


def test_workspace_write_requires_observed_artifact_and_records_tool_errors(tmp_path):
    def ready(*_args):
        return _ready()

    class NoWrite:
        pid = 701
        returncode = 0

        def communicate(self, input=None, timeout=None):
            return "\n".join((
                json.dumps({"type": "thread.started", "thread_id": "no-write"}),
                json.dumps({"type": "item.completed", "item": {
                    "type": "agent_message", "text": "claimed completion",
                }}),
                json.dumps({"type": "turn.completed", "usage": {}}),
            )), ""

    failed, failed_code, _out, _err = _run_codex(
        "write a report", tmp_path, sandbox="workspace-write",
        preflight_fn=ready, popen_impl=lambda *_args, **_kwargs: NoWrite(),
        expected_artifact_paths=("report.md",),
    )
    assert failed_code == 1
    assert failed["is_error"] is True
    assert failed["model_receipt"]["status"] == "artifact_required"
    assert failed["model_receipt"]["artifact_write_observed"] is False

    class WritesInside:
        pid = 702
        returncode = 0

        def communicate(self, input=None, timeout=None):
            (tmp_path / "report.md").write_text("verified report\n", encoding="utf-8")
            return "\n".join((
                json.dumps({"type": "thread.started", "thread_id": "with-write"}),
                json.dumps({"type": "item.completed", "item": {
                    "type": "agent_message", "text": "report complete",
                }}),
                json.dumps({"type": "turn.completed", "usage": {
                    "input_tokens": 1, "output_tokens": 1,
                }}),
            )), (
                "2026-08-30 ERROR codex_core::tools::router: error="
                "an out-of-scope recovery attempt was denied"
            )

    passed, passed_code, _out, _err = _run_codex(
        "write a report", tmp_path, sandbox="workspace-write",
        preflight_fn=ready, popen_impl=lambda *_args, **_kwargs: WritesInside(),
        expected_artifact_paths=("report.md",),
    )
    receipt = passed["model_receipt"]
    assert passed_code == 0 and passed["is_error"] is False
    assert receipt["status"] == "success"
    assert receipt["artifact_write_observed"] is True
    assert receipt["artifact_paths"] == ["report.md"]
    assert receipt["expected_artifact_paths"] == ["report.md"]
    assert receipt["artifact_contract_verified"] is True
    assert receipt["artifact_mutation_verified"] is True
    assert receipt["artifact_contract_verified"] == \
        receipt["artifact_mutation_verified"]
    assert receipt["artifact_hashes"]["report.md"] == \
        ca.hashlib.sha256((tmp_path / "report.md").read_bytes()).hexdigest()
    assert receipt["artifact_evidence"]["report.md"]["sha256"] == \
        receipt["artifact_hashes"]["report.md"]
    assert receipt["tool_error_count"] == 1
    assert "error" not in receipt


def test_workspace_write_without_contract_refuses_before_preflight_or_spawn(tmp_path):
    def forbidden(*_args, **_kwargs):
        raise AssertionError("a paid seat must not start without an artifact contract")

    envelope, code, out, err = _run_codex(
        "write something", tmp_path, sandbox="workspace-write",
        preflight_fn=forbidden, popen_impl=forbidden,
    )
    receipt = envelope["model_receipt"]
    assert code == 2 and out == err == ""
    assert receipt["status"] == "artifact_contract_required"
    assert receipt["seat_started"] is False
    assert receipt["artifact_contract_verified"] is False
    assert receipt["artifact_mutation_verified"] is False


@pytest.mark.parametrize("unsafe", [
    "report.md:proof", "*.md", "part?.md", "[abc].md", "{a,b}.md",
    'less<than.md', 'greater>than.md', 'quote".md', "pipe|.md",
    "line\nbreak.md", "delete\x7f.md", "folder\\report.md", "CON",
    "nul.txt", "CONIN$", "CONOUT$.txt", "folder/COM1.log", "COM¹.txt",
    "LPT²", "name.", "name ", "a//b.md",
    "a/./b.md", "a/../b.md", "/absolute/report.md", "e\u0301.md",
])
def test_expected_artifact_contract_rejects_nonportable_paths(tmp_path, unsafe):
    with pytest.raises(ValueError):
        ca._normalize_expected_artifacts(tmp_path, (unsafe,))


def test_expected_artifact_contract_enforces_case_count_and_byte_caps(
        tmp_path, monkeypatch):
    for nontext in (b"report.md", 7, None):
        with pytest.raises(ValueError, match="text"):
            ca._normalize_expected_artifacts(tmp_path, (nontext,))
    with pytest.raises(ValueError, match="case-equivalent"):
        ca._normalize_expected_artifacts(tmp_path, ("Report.md", "report.md"))
    with pytest.raises(ValueError, match="count"):
        ca._normalize_expected_artifacts(
            tmp_path, tuple("%02d.md" % value for value in range(33)))
    path_over_cap = "/".join(("a" * 171, "b" * 170, "c" * 170))
    with pytest.raises(ValueError, match="path bytes"):
        ca._normalize_expected_artifacts(tmp_path, (path_over_cap,))
    total_over_cap = tuple(
        "%02d-%s.md" % (value, "z" * 145) for value in range(28))
    with pytest.raises(ValueError, match="path bytes"):
        ca._normalize_expected_artifacts(tmp_path, total_over_cap)

    monkeypatch.setattr(ca, "MAX_EXPECTED_PATH_BYTES", 5)
    with pytest.raises(ValueError, match="path bytes"):
        ca._normalize_expected_artifacts(tmp_path, ("report.md",))


def test_existing_link_component_is_not_resolved_out_of_the_contract(
        tmp_path):
    real = tmp_path / "real"
    real.mkdir()
    link = tmp_path / "linked"
    try:
        link.symlink_to(real, target_is_directory=True)
    except OSError:
        pytest.skip("directory symlinks are unavailable on this host")
    normalized = ca._normalize_expected_artifacts(
        tmp_path, ("linked/report.md",))
    assert normalized == ("linked/report.md",)
    snapshot, complete = ca._expected_artifact_snapshot(tmp_path, normalized)
    assert snapshot == {}
    assert complete is False


def test_expected_artifact_reparse_and_hardlink_evidence_fail_closed(
        tmp_path):
    assert ca._is_reparse(SimpleNamespace(st_file_attributes=0x400)) is True
    assert ca._is_reparse(SimpleNamespace(st_file_attributes=0)) is False

    original = tmp_path / "original.md"
    alias = tmp_path / "alias.md"
    original.write_text("same inode", encoding="utf-8")
    try:
        os.link(original, alias)
    except OSError:
        pytest.skip("hard links are unavailable on this host")
    one, one_complete = ca._expected_artifact_snapshot(
        tmp_path, ("original.md",))
    assert one == {}
    assert one_complete is False
    aliases, aliases_complete = ca._expected_artifact_snapshot(
        tmp_path, ("alias.md", "original.md"))
    assert aliases == {}
    assert aliases_complete is False


def test_reparse_attribute_is_rejected_at_component_boundary(
        tmp_path, monkeypatch):
    expected = tmp_path / "report.md"
    expected.write_text("bytes", encoding="utf-8")
    real_lstat = Path.lstat

    def reparse_lstat(path):
        observed = real_lstat(path)
        if Path(path) == expected:
            return SimpleNamespace(
                st_mode=observed.st_mode,
                st_file_attributes=0x400,
            )
        return observed

    monkeypatch.setattr(Path, "lstat", reparse_lstat)
    assert ca._artifact_components_safe(tmp_path, "report.md") is False


def test_expected_artifact_per_file_and_total_byte_caps_fail_closed(
        tmp_path, monkeypatch):
    (tmp_path / "one.md").write_bytes(b"1234")
    monkeypatch.setattr(ca, "MAX_ARTIFACT_BYTES", 3)
    snapshot, complete = ca._expected_artifact_snapshot(tmp_path, ("one.md",))
    assert snapshot == {}
    assert complete is False

    monkeypatch.setattr(ca, "MAX_ARTIFACT_BYTES", 10)
    monkeypatch.setattr(ca, "MAX_ARTIFACT_TOTAL_BYTES", 5)
    (tmp_path / "two.md").write_bytes(b"5678")
    snapshot, complete = ca._expected_artifact_snapshot(
        tmp_path, ("one.md", "two.md"))
    assert complete is False
    assert snapshot["one.md"]["size"] == 4


def test_internal_launch_pointer_name_is_rejected_case_insensitively(tmp_path):
    for spelling in ("launch.pointer.json", "Launch.Pointer.JSON"):
        with pytest.raises(ValueError, match="eligible"):
            ca._normalize_expected_artifacts(tmp_path, (spelling,))


def test_workspace_root_identity_guard_blocks_or_detects_replacement(
        tmp_path, monkeypatch):
    opened = []
    real_open = ca._open_guarded_directory

    def recording_open(path):
        guard = real_open(path)
        opened.append(guard)
        return guard

    monkeypatch.setattr(ca, "_open_guarded_directory", recording_open)
    moved = tmp_path.parent / (tmp_path.name + "-moved")
    state = {"rename_blocked": False}

    class ReplacesRoot:
        pid = 707
        returncode = 0

        def communicate(self, input=None, timeout=None):
            try:
                tmp_path.rename(moved)
            except OSError:
                state["rename_blocked"] = True
                (tmp_path / "report.md").write_text("guarded", encoding="utf-8")
            else:
                tmp_path.mkdir()
                (tmp_path / "report.md").write_text(
                    "unrelated replacement", encoding="utf-8")
            return _success_stream("claimed"), ""

    envelope, code, _out, _err = _run_codex(
        "write report", tmp_path, sandbox="workspace-write",
        expected_artifact_paths=("report.md",),
        preflight_fn=lambda *_args: _ready(),
        popen_impl=lambda *_args, **_kwargs: ReplacesRoot(),
    )
    receipt = envelope["model_receipt"]
    assert opened and opened[0].closed is True
    if state["rename_blocked"]:
        assert code == 0 and receipt["artifact_mutation_verified"] is True
    else:
        assert code == 1 and receipt["status"] == "artifact_scan_incomplete"
        assert receipt["artifact_mutation_verified"] is False


def test_artifact_prescan_baseexception_releases_root_guard_without_spawning(
        tmp_path, monkeypatch):
    state = {"closed": False}

    class Guard:
        def fileno(self):
            return 1

        def close(self):
            state["closed"] = True

    monkeypatch.setattr(ca, "_open_guarded_directory", lambda _path: Guard())
    monkeypatch.setattr(ca, "_guarded_directory_identity", lambda *_args: (1, 1))
    monkeypatch.setattr(ca, "_workspace_root_matches", lambda *_args: True)
    monkeypatch.setattr(
        ca, "_expected_artifact_snapshot",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(KeyboardInterrupt()))

    envelope, code, _out, _err = _run_codex(
        "write report", tmp_path, sandbox="workspace-write",
        expected_artifact_paths=("report.md",),
        preflight_fn=lambda *_args: _ready(),
        popen_impl=lambda *_args, **_kwargs: pytest.fail("must not spawn"),
    )
    assert code == 130 and state["closed"] is True
    assert envelope["model_receipt"]["status"] == "artifact_scan_incomplete"
    assert envelope["model_receipt"]["aborted"] is True


def test_every_expected_artifact_must_hash_change_and_aliases_stay_equal(tmp_path):
    first = tmp_path / "first.md"
    second = tmp_path / "second.md"
    first.write_text("before", encoding="utf-8")
    second.write_text("unchanged", encoding="utf-8")

    class PartialMutation:
        pid = 706
        returncode = 0

        def communicate(self, input=None, timeout=None):
            first.write_text("after", encoding="utf-8")
            # Rewriting identical bytes is not an artifact mutation.
            second.write_text("unchanged", encoding="utf-8")
            return _success_stream("claimed"), ""

    envelope, code, _out, _err = _run_codex(
        "update both reports", tmp_path, sandbox="workspace-write",
        expected_artifact_paths=("first.md", "second.md"),
        preflight_fn=lambda *_args: _ready(),
        popen_impl=lambda *_args, **_kwargs: PartialMutation(),
    )
    receipt = envelope["model_receipt"]
    assert code == 1 and receipt["status"] == "artifact_required"
    assert receipt["artifact_paths"] == ["first.md"]
    assert receipt["artifact_mutation_verified"] is False
    assert receipt["artifact_contract_verified"] is False

    direct = ca.build_receipt(
        status="success", prompt="x", sandbox="workspace-write", preflight={},
        artifact_contract_verified=True, artifact_mutation_verified=False)
    assert direct["artifact_contract_verified"] is False
    assert direct["artifact_contract_verified"] == \
        direct["artifact_mutation_verified"]


def test_arbitrary_mutation_cannot_satisfy_expected_artifact_contract(tmp_path):
    class WritesWrongFile:
        pid = 703
        returncode = 0

        def communicate(self, input=None, timeout=None):
            (tmp_path / "unrelated.tmp").write_text("wrong", encoding="utf-8")
            return _success_stream("claimed"), ""

    envelope, code, _out, _err = _run_codex(
        "write REQUIRED.md", tmp_path, sandbox="workspace-write",
        expected_artifact_paths=("REQUIRED.md",),
        preflight_fn=lambda *_args: _ready(),
        popen_impl=lambda *_args, **_kwargs: WritesWrongFile(),
    )
    receipt = envelope["model_receipt"]
    assert code == 1 and receipt["status"] == "artifact_required"
    assert receipt["artifact_paths"] == []
    assert receipt["artifact_hashes"] == {}


def test_artifact_sha_detects_change_when_size_and_mtime_are_spoofed(tmp_path):
    expected = tmp_path / "report.md"
    expected.write_bytes(b"AAAA")
    original = expected.stat()

    class SpoofsMetadata:
        pid = 704
        returncode = 0

        def communicate(self, input=None, timeout=None):
            expected.write_bytes(b"BBBB")
            os.utime(expected, ns=(original.st_atime_ns, original.st_mtime_ns))
            return _success_stream("done"), ""

    envelope, code, _out, _err = _run_codex(
        "update report.md", tmp_path, sandbox="workspace-write",
        expected_artifact_paths=("report.md",),
        preflight_fn=lambda *_args: _ready(),
        popen_impl=lambda *_args, **_kwargs: SpoofsMetadata(),
    )
    receipt = envelope["model_receipt"]
    assert code == 0 and receipt["artifact_contract_verified"] is True
    assert receipt["artifact_hashes"] == {
        "report.md": ca.hashlib.sha256(b"BBBB").hexdigest(),
    }


def test_expected_artifact_symlink_redirect_after_launch_fails_containment(tmp_path):
    outside = tmp_path.parent / (tmp_path.name + "-outside.txt")
    outside.write_text("outside", encoding="utf-8")
    link = tmp_path / "report.md"
    try:
        link.symlink_to(outside)
        link.unlink()
    except OSError:
        pytest.skip("file symlinks are unavailable on this host")

    class RedirectsExpectedPath:
        pid = 705
        returncode = 0

        def communicate(self, input=None, timeout=None):
            link.symlink_to(outside)
            return _success_stream("claimed"), ""

    envelope, code, _out, _err = _run_codex(
        "write report.md", tmp_path, sandbox="workspace-write",
        expected_artifact_paths=("report.md",),
        preflight_fn=lambda *_args: _ready(),
        popen_impl=lambda *_args, **_kwargs: RedirectsExpectedPath(),
    )
    assert code == 1
    assert envelope["model_receipt"]["status"] == "artifact_scan_incomplete"
    assert envelope["model_receipt"]["artifact_contract_verified"] is False


def test_preflight_failure_never_spawns_a_seat(tmp_path):
    def no_spawn(*_args, **_kwargs):
        raise AssertionError("seat must not spawn")

    envelope, code, native_out, native_err = _run_codex(
        "work", tmp_path, env={"ANCHOR_CODEX_CMD": "missing-codex"},
        preflight_fn=lambda *_args: {
            "ok": False,
            "status": "subscription_auth_required",
            "executable_path": "missing-codex",
            "auth_probe_at": "now",
            "subscription_auth": False,
            "error": "not logged in using ChatGPT",
        },
        popen_impl=no_spawn,
    )
    assert code == 2 and native_out == native_err == ""
    assert envelope["is_error"] is True
    assert envelope["model_receipt"]["status"] == "subscription_auth_required"
    assert envelope["model_receipt"]["transport_actual"] is None
    assert envelope["model_receipt"]["billing_mode"] is None
    assert envelope["model_receipt"]["cost_state"] == "no_seat_started"
    assert envelope["model_receipt"]["seat_started"] is False

    authenticated_no_seat = ca.build_receipt(
        status="capability_unavailable", prompt="work", sandbox="read-only",
        preflight={
            "transport_actual": "codex-cli",
            "auth_kind": "chatgpt_subscription",
            "subscription_auth": True,
            "model_capability_verified": False,
            "ultra_capability_verified": False,
        },
        seat_started=False,
    )
    assert authenticated_no_seat["billing_mode"] is None
    assert authenticated_no_seat["cost_state"] == "no_seat_started"


def test_timeout_kills_and_bounds_the_post_kill_drain(tmp_path, monkeypatch):
    calls = {"communicate": 0, "kill": 0}

    class NeverDrains:
        pid = 321
        returncode = 9

        def communicate(self, input=None, timeout=None):
            calls["communicate"] += 1
            raise subprocess.TimeoutExpired("codex", timeout)

    def fake_popen(_argv, **_kwargs):
        return NeverDrains()

    def fake_kill(_proc, _pgid=None, _platform=None):
        calls["kill"] += 1
        return True

    monkeypatch.setattr(ca, "_kill_tree", fake_kill)
    envelope, code, _native_out, native_err = _run_codex(
        "work", tmp_path, timeout_seconds=0.01,
        preflight_fn=lambda *_args: _ready(),
        popen_impl=fake_popen,
    )
    assert code == 1
    assert envelope["model_receipt"]["status"] == "kill_failed"
    assert envelope["model_receipt"]["timed_out"] is True
    assert envelope["model_receipt"]["tree_kill_verified"] is False
    assert envelope["model_receipt"]["output_drain_verified"] is False
    assert calls == {"communicate": 2, "kill": 2}
    assert "did not drain" in native_err


def test_timeout_fails_closed_when_tree_death_is_not_verified(tmp_path, monkeypatch):
    class TimesOutThenDrains:
        pid = 987
        returncode = 9
        attempts = 0

        def communicate(self, input=None, timeout=None):
            self.attempts += 1
            if self.attempts == 1:
                raise subprocess.TimeoutExpired("codex", timeout)
            return "", ""

    monkeypatch.setattr(ca, "_kill_tree", lambda *_args: False)
    envelope, code, _out, _err = _run_codex(
        "work", tmp_path, timeout_seconds=0.01,
        preflight_fn=lambda *_args: _ready(),
        popen_impl=lambda *_args, **_kwargs: TimesOutThenDrains(),
    )
    receipt = envelope["model_receipt"]
    assert code == 1
    assert receipt["status"] == "kill_failed"
    assert receipt["timed_out"] is True
    assert receipt["tree_kill_verified"] is False
    assert "not both verified" in receipt["error"]


def test_windows_tree_kill_requires_verified_job_membership(monkeypatch):
    class Proc:
        pid = 456

        def __init__(self):
            self.returncode = None
            self.direct_kills = 0

        def poll(self):
            return self.returncode

        def wait(self, timeout=None):
            self.returncode = 1
            return 1

        def kill(self):
            self.direct_kills += 1
            self.returncode = 1

    class Job:
        membership_verified = True

        def terminate_verified(self, proc):
            proc.returncode = 1
            return True

    successful = Proc()
    successful._anchor_windows_job = Job()
    monkeypatch.setattr(ca.subprocess, "run", lambda *_args, **_kwargs: (
        pytest.fail("taskkill must not be used")))
    assert ca._kill_tree(successful, platform_name="nt") is True
    assert successful.direct_kills == 0

    refused = Proc()
    assert ca._kill_tree(refused, platform_name="nt") is False
    assert refused.direct_kills == 1


def test_windows_launch_is_suspended_owned_then_resumed_from_trusted_cwd(tmp_path):
    events = []

    class Job(_FakeWindowsJob):
        def __init__(self):
            events.append("job-policy")
            super().__init__()

        def assign_and_resume(self, proc, cancel_before_resume=False):
            events.append("job-assign")
            result = super().assign_and_resume(proc, cancel_before_resume)
            events.append("job-resume" if result else "job-cancel")
            return result

        def verify_empty(self):
            events.append("job-empty")
            return super().verify_empty()

    class Child:
        pid = 457
        returncode = 0

        def communicate(self, input=None, timeout=None):
            events.append("communicate")
            return _success_stream("OWNED"), ""

        def poll(self):
            return self.returncode

    def popen(argv, **kwargs):
        events.append("popen")
        assert kwargs["creationflags"] & ca._WindowsJob.CREATE_SUSPENDED
        assert kwargs["close_fds"] is True
        assert kwargs["executable"] == argv[0]
        assert Path(kwargs["cwd"]) == Path(argv[0]).parent
        assert kwargs["start_new_session"] is False
        return Child()

    envelope, code, _out, _err = _run_codex(
        "work", tmp_path, preflight_fn=lambda *_args: _ready(),
        popen_impl=popen, platform_name="nt", windows_job_factory=Job,
    )
    assert code == 0 and envelope["result"] == "OWNED"
    assert events.index("job-policy") < events.index("popen") < \
        events.index("job-assign") < events.index("job-resume") < \
        events.index("communicate")
    receipt = envelope["model_receipt"]
    assert receipt["containment_kind"] == "windows_job"
    assert receipt["windows_job_policy_verified"] is True
    assert receipt["windows_job_assignment_verified"] is True
    assert receipt["windows_job_membership_verified"] is True
    assert receipt["windows_process_handle_verified"] is True
    assert receipt["windows_primary_thread_verified"] is True
    assert receipt["windows_process_resumed"] is True
    assert receipt["windows_job_empty_verified"] is True
    assert receipt["complete_tree_containment"] is True


def test_windows_unverified_job_policy_refuses_before_spawn(tmp_path):
    events = []

    class UnverifiedJob(_FakeWindowsJob):
        policy_verified = False

        def close(self):
            events.append("close")
            super().close()

    def no_spawn(*_args, **_kwargs):
        events.append("spawn")
        raise AssertionError("unverified Job policy must refuse before Popen")

    envelope, code, _out, _err = _run_codex(
        "work", tmp_path, preflight_fn=lambda *_args: _ready(),
        popen_impl=no_spawn, platform_name="nt",
        windows_job_factory=UnverifiedJob,
    )
    receipt = envelope["model_receipt"]
    assert code == 2 and receipt["status"] == "containment_assignment_failed"
    assert receipt["seat_started"] is False
    assert events == ["close"]


@pytest.mark.parametrize("abort_verified, expected_status", [
    (True, "containment_assignment_failed"),
    (False, "kill_failed"),
])
def test_windows_assignment_or_thread_verification_failure_never_resumes(
        tmp_path, abort_verified, expected_status):
    events = []

    class FailingJob(_FakeWindowsJob):
        def assign_and_resume(self, _proc, cancel_before_resume=False):
            self.process_handle_verified = True
            self.assigned = True
            self.membership_verified = True
            events.append("membership")
            raise OSError("primary thread identity mismatch")

        def abort_suspended(self, proc):
            events.append("abort-suspended")
            self.empty_verified = abort_verified
            proc.returncode = -9 if abort_verified else None
            return abort_verified

    class Child:
        pid = 458
        returncode = None

        def communicate(self, input=None, timeout=None):
            events.append("drain")
            return "", ""

        def poll(self):
            return self.returncode

        def wait(self, timeout=None):
            if self.returncode is None:
                raise subprocess.TimeoutExpired("codex", timeout)
            return self.returncode

    envelope, code, _out, _err = _run_codex(
        "work", tmp_path, preflight_fn=lambda *_args: _ready(),
        popen_impl=lambda *_args, **_kwargs: Child(), platform_name="nt",
        windows_job_factory=FailingJob,
    )
    receipt = envelope["model_receipt"]
    assert code == 1 and receipt["status"] == expected_status
    assert events == ["membership", "abort-suspended", "drain"]
    assert receipt["windows_process_resumed"] is False
    assert receipt["seat_started"] is False
    assert receipt["output_drain_verified"] is True
    assert receipt["tree_kill_verified"] is abort_verified


def test_windows_already_runnable_thread_is_billed_and_killed_as_started(tmp_path):
    class ExecutionPossibleJob(_FakeWindowsJob):
        def assign_and_resume(self, _proc, cancel_before_resume=False):
            self.process_handle_verified = True
            self.assigned = True
            self.membership_verified = True
            self.primary_thread_verified = True
            self.execution_possible = True
            raise OSError("ResumeThread found an already-runnable process")

        def abort_suspended(self, proc):
            self.empty_verified = True
            proc.returncode = -9
            return True

    class Child:
        pid = 463
        returncode = None

        def communicate(self, input=None, timeout=None):
            return "", ""

        def poll(self):
            return self.returncode

    envelope, code, _out, _err = _run_codex(
        "work", tmp_path, preflight_fn=lambda *_args: _ready(),
        popen_impl=lambda *_args, **_kwargs: Child(), platform_name="nt",
        windows_job_factory=ExecutionPossibleJob,
    )
    receipt = envelope["model_receipt"]
    assert code == 1 and receipt["status"] == "containment_assignment_failed"
    assert receipt["seat_started"] is True
    assert receipt["billing_mode"] == "subscription"
    assert receipt["windows_process_resumed"] is False
    assert receipt["windows_execution_possible"] is True
    assert receipt["tree_kill_verified"] is True


def test_windows_signal_after_membership_is_rechecked_before_resume(tmp_path):
    events = []

    class Signals:
        SIGTERM = 15
        SIGINT = 2

        def __init__(self):
            self.handlers = {}

        def getsignal(self, signum):
            return "old-%s" % signum

        def signal(self, signum, handler):
            self.handlers[signum] = handler

    signals = Signals()

    class CancelAtResume(_FakeWindowsJob):
        def assign_and_resume(self, _proc, cancel_before_resume=False):
            self.process_handle_verified = True
            self.assigned = True
            self.membership_verified = True
            self.primary_thread_verified = True
            events.append("membership")
            signals.handlers[signals.SIGINT](signals.SIGINT, None)
            events.append("pre-resume-cancel-check")
            assert callable(cancel_before_resume)
            assert cancel_before_resume() is True
            return False

        def terminate_verified(self, proc, timeout_seconds=5.0):
            events.append("terminate-job")
            self.empty_verified = True
            proc.returncode = -9
            return True

    class Child:
        pid = 459
        returncode = None

        def communicate(self, input=None, timeout=None):
            events.append("drain")
            return "", ""

        def poll(self):
            return self.returncode

    envelope, code, _out, _err = _run_codex(
        "work", tmp_path, preflight_fn=lambda *_args: _ready(),
        popen_impl=lambda *_args, **_kwargs: Child(), platform_name="nt",
        signal_api=signals, windows_job_factory=CancelAtResume,
    )
    receipt = envelope["model_receipt"]
    assert code == 130 and receipt["status"] == "aborted"
    assert events == [
        "membership", "pre-resume-cancel-check", "terminate-job", "drain"]
    assert receipt["windows_process_resumed"] is False
    assert receipt["seat_started"] is False
    assert receipt["tree_kill_verified"] is True
    assert receipt["output_drain_verified"] is True


def test_windows_signal_immediately_after_resume_cannot_unwind_cleanup(tmp_path):
    events = []

    class Signals:
        SIGTERM = 15
        SIGINT = 2

        def __init__(self):
            self.handlers = {}

        def getsignal(self, signum):
            return "old-%s" % signum

        def signal(self, signum, handler):
            self.handlers[signum] = handler

    signals = Signals()

    class SignalAfterResume(_FakeWindowsJob):
        def assign_and_resume(self, proc, cancel_before_resume=False):
            result = super().assign_and_resume(proc, cancel_before_resume)
            events.append("resumed")
            signals.handlers[signals.SIGINT](signals.SIGINT, None)
            events.append("handler-returned")
            return result

        def terminate_verified(self, proc, timeout_seconds=5.0):
            events.append("terminate-job")
            self.empty_verified = True
            proc.returncode = -9
            return True

    class Child:
        pid = 462
        returncode = None

        def communicate(self, input=None, timeout=None):
            events.append("drain")
            return "", ""

        def poll(self):
            return self.returncode

    envelope, code, _out, _err = _run_codex(
        "work", tmp_path, preflight_fn=lambda *_args: _ready(),
        popen_impl=lambda *_args, **_kwargs: Child(), platform_name="nt",
        signal_api=signals, windows_job_factory=SignalAfterResume,
    )
    receipt = envelope["model_receipt"]
    assert events[:3] == ["resumed", "terminate-job", "handler-returned"]
    assert "drain" in events
    assert code == 130 and receipt["status"] == "aborted"
    assert receipt["seat_started"] is True
    assert receipt["windows_execution_possible"] is True
    assert receipt["tree_kill_verified"] is True


def test_windows_normal_exit_with_job_straggler_is_not_success(tmp_path):
    class StragglerJob(_FakeWindowsJob):
        def verify_empty(self):
            self.empty_verified = False
            return False

        def terminate_verified(self, _proc, timeout_seconds=5.0):
            self.empty_verified = True
            return True

    class Child:
        pid = 460
        returncode = 0

        def communicate(self, input=None, timeout=None):
            return _success_stream("claimed success"), ""

        def poll(self):
            return self.returncode

    envelope, code, _out, _err = _run_codex(
        "work", tmp_path, preflight_fn=lambda *_args: _ready(),
        popen_impl=lambda *_args, **_kwargs: Child(), platform_name="nt",
        windows_job_factory=StragglerJob,
    )
    receipt = envelope["model_receipt"]
    assert code == 1 and receipt["status"] == "process_tree_straggler"
    assert receipt["windows_job_empty_verified"] is True
    assert receipt["tree_kill_verified"] is True


def test_windows_job_close_baseexception_is_contained_and_fails_closed(tmp_path):
    class CloseFails(_FakeWindowsJob):
        def close(self):
            raise SystemExit(8)

    class Child:
        pid = 464
        returncode = 0

        def communicate(self, input=None, timeout=None):
            return _success_stream("claimed"), ""

        def poll(self):
            return self.returncode

    envelope, code, _out, _err = _run_codex(
        "work", tmp_path, preflight_fn=lambda *_args: _ready(),
        popen_impl=lambda *_args, **_kwargs: Child(), platform_name="nt",
        windows_job_factory=CloseFails,
    )
    assert code == 1
    assert envelope["model_receipt"]["status"] == "kill_failed"


def test_posix_process_group_death_is_not_complete_tree_proof(monkeypatch):
    state = {"dead": False}

    class Proc:
        pid = 461
        returncode = None

        def poll(self):
            return self.returncode

        def wait(self, timeout=None):
            if self.returncode is None:
                raise subprocess.TimeoutExpired("codex", timeout)
            return self.returncode

    proc = Proc()

    def killpg(pgid, signum):
        assert pgid == proc.pid
        if signum == 0:
            if state["dead"]:
                raise ProcessLookupError()
            return
        assert signum == ca.signal.SIGKILL
        state["dead"] = True
        proc.returncode = -9

    monkeypatch.setattr(ca.os, "getpgid", lambda pid: pid, raising=False)
    monkeypatch.setattr(ca.os, "killpg", killpg, raising=False)
    monkeypatch.setattr(ca.signal, "SIGKILL", 9, raising=False)
    assert ca._kill_tree(proc, posix_pgid=proc.pid, platform_name="posix") is False
    assert proc._anchor_process_group_kill_verified is True


@pytest.mark.skipif(os.name != "nt", reason="real Windows Job Object canary")
def test_real_windows_job_owns_resumes_and_cancels_suspended_python(tmp_path):
    executable = str(Path(sys.executable).resolve())
    creationflags = (
        ca._WindowsJob.CREATE_SUSPENDED |
        getattr(subprocess, "CREATE_NO_WINDOW", 0)
    )

    def spawn(marker):
        code = (
            "from pathlib import Path; import sys; "
            "Path(sys.argv[1]).write_text('ran', encoding='utf-8')"
        )
        return subprocess.Popen(
            [executable, "-c", code, str(marker)],
            executable=executable, cwd=str(Path(executable).parent),
            stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, env=ca.subscription_only_env({}),
            shell=False, close_fds=True, text=True, encoding="utf-8",
            errors="replace", creationflags=creationflags,
        )

    normal_marker = tmp_path / "normal-ran.txt"
    normal_job = ca._WindowsJob()
    normal = None
    try:
        normal = spawn(normal_marker)
        assert normal_job.assign_and_resume(normal) is True
        _out, err = normal.communicate(timeout=15)
        assert normal.returncode == 0, err
        assert normal_marker.read_text(encoding="utf-8") == "ran"
        assert normal_job.assigned is True
        assert normal_job.membership_verified is True
        assert normal_job.process_handle_verified is True
        assert normal_job.primary_thread_verified is True
        assert normal_job.execution_possible is True
        assert normal_job.resumed is True
        assert normal_job.verify_empty() is True
    finally:
        if normal is not None and normal.poll() is None:
            normal_job.abort_suspended(normal)
            normal.communicate(timeout=15)
        normal_job.close()

    cancelled_marker = tmp_path / "cancelled-must-not-run.txt"
    cancelled_job = ca._WindowsJob()
    cancelled = None
    try:
        cancelled = spawn(cancelled_marker)
        assert cancelled_job.assign_and_resume(
            cancelled, cancel_before_resume=lambda: True) is False
        assert cancelled_job.execution_possible is False
        assert cancelled_job.resumed is False
        assert cancelled_job.abort_suspended(cancelled) is True
        cancelled.communicate(timeout=15)
        assert cancelled_marker.exists() is False
        assert cancelled_job.verify_empty() is True
    finally:
        if cancelled is not None and cancelled.poll() is None:
            cancelled_job.abort_suspended(cancelled)
            cancelled.communicate(timeout=15)
        cancelled_job.close()


def test_keyboard_interrupt_during_popen_never_trusts_exception_process(
        tmp_path, monkeypatch):
    events = []

    class Child:
        pid = 888
        returncode = -9

        def communicate(self, input=None, timeout=None):
            events.append(("drain", timeout))
            return "", ""

    child = Child()

    class InterruptedSpawn(KeyboardInterrupt):
        def __init__(self):
            super().__init__("cancelled during Popen")
            self.process = child

    def interrupted(*_args, **_kwargs):
        raise InterruptedSpawn()

    monkeypatch.setattr(
        ca, "_kill_tree",
        lambda proc, _pgid=None, _platform=None: (
            events.append(("kill", proc.pid)) or True))
    envelope, code, _out, _err = _run_codex(
        "work", tmp_path, preflight_fn=lambda *_args: _ready(),
        popen_impl=interrupted,
    )
    receipt = envelope["model_receipt"]
    assert code == 130 and receipt["status"] == "spawn_aborted"
    assert receipt["seat_started"] is False
    assert receipt["tree_kill_verified"] is None
    assert receipt["output_drain_verified"] is None
    assert events == []


def test_spawn_interruption_with_undrained_pipe_cannot_claim_verified_tree(
        tmp_path, monkeypatch):
    class Child:
        pid = 890
        returncode = -9

        def communicate(self, input=None, timeout=None):
            raise subprocess.TimeoutExpired("codex", timeout)

    class InterruptedSpawn(KeyboardInterrupt):
        def __init__(self):
            super().__init__("cancelled")
            self.process = Child()

    monkeypatch.setattr(ca, "_kill_tree", lambda *_args: True)
    envelope, code, _out, _err = _run_codex(
        "work", tmp_path, preflight_fn=lambda *_args: _ready(),
        popen_impl=lambda *_args, **_kwargs: (_ for _ in ()).throw(
            InterruptedSpawn()),
    )
    receipt = envelope["model_receipt"]
    assert code == 130 and receipt["status"] == "spawn_aborted"
    assert receipt["seat_started"] is False
    assert receipt["tree_kill_verified"] is None
    assert receipt["output_drain_verified"] is None


def test_windows_signal_during_popen_is_deferred_until_child_is_owned(
        tmp_path, monkeypatch):
    events = []

    class WindowsSignals:
        SIGTERM = 15
        SIGINT = 2

        def __init__(self):
            self.handlers = {}

        def getsignal(self, signum):
            return "old-%s" % signum

        def signal(self, signum, handler):
            self.handlers[signum] = handler
            events.append(("handler", signum))

    signals = WindowsSignals()

    class Child:
        pid = 889
        returncode = -9

        def communicate(self, input=None, timeout=None):
            events.append(("drain", timeout))
            return "", ""

    def interrupted_window(*_args, **_kwargs):
        events.append(("popen", "before-signal"))
        signals.handlers[signals.SIGINT](signals.SIGINT, None)
        events.append(("popen", "return"))
        return Child()

    monkeypatch.setattr(ca, "_kill_tree", lambda proc, _pgid=None, _platform=None: (
        events.append(("kill", proc.pid)) or True))
    envelope, code, _out, _err = _run_codex(
        "work", tmp_path, preflight_fn=lambda *_args: _ready(),
        popen_impl=interrupted_window, platform_name="nt", signal_api=signals,
    )
    receipt = envelope["model_receipt"]
    assert code == 130 and receipt["status"] == "aborted"
    assert events.index(("popen", "return")) < events.index(("kill", 889))
    assert receipt["tree_kill_verified"] is True
    assert receipt["output_drain_verified"] is True


def test_security_receipt_booleans_are_evidence_derived_not_defaults():
    receipt = ca.build_receipt(
        status="preflight_failed", prompt="work", sandbox="read-only",
        preflight={
            "config_guard_verified": True,
            "subscription_auth": False,
            "config_fingerprint": {
                "exists": True, "sha256": "ignored-mutable-config",
            },
        },
    )
    assert receipt["user_config_loaded"] is False
    assert receipt["config_sha256"] is None
    for key in (
            "critical_overrides_enforced", "rules_ignored", "agents_disabled",
            "network_disabled", "extra_writable_roots_disabled",
            "hosted_tools_disabled", "mcp_servers_disabled",
            "api_key_env_scrubbed", "runtime_guard_rechecked"):
        assert receipt[key] is False


class _FakePosixSignals:
    SIG_BLOCK = 1
    SIG_SETMASK = 2
    SIGTERM = 15
    SIGINT = 2

    def __init__(self, events, deliver_pending=False):
        self.events = events
        self.handlers = {}
        self.deliver_pending = deliver_pending
        self.delivered = False

    def pthread_sigmask(self, how, mask):
        self.events.append(("mask", how, frozenset(mask or ())))
        if (how == self.SIG_SETMASK and self.deliver_pending
                and not self.delivered):
            self.delivered = True
            self.events.append(("deliver", self.SIGTERM))
            self.handlers[self.SIGTERM](self.SIGTERM, None)
        return frozenset((99,))

    def getsignal(self, sig):
        self.events.append(("get", sig))
        return "old-%s" % sig

    def signal(self, sig, handler):
        self.events.append(("handler", sig, handler))
        self.handlers[sig] = handler


def _success_stream(message="POSIX_OK"):
    return "\n".join((
        json.dumps({"type": "thread.started", "thread_id": "posix-thread"}),
        json.dumps({"type": "item.completed", "item": {
            "type": "agent_message", "text": message,
        }}),
        json.dumps({"type": "turn.completed", "usage": {}}),
    ))


def test_posix_signal_guard_blocks_before_spawn_and_restores_after_drain(tmp_path):
    events = []
    fake_signals = _FakePosixSignals(events)

    class Proc:
        pid = 654
        returncode = 0

        def communicate(self, input=None, timeout=None):
            events.append(("communicate", input))
            return _success_stream(), ""

    def popen(_argv, **kwargs):
        events.append(("popen", kwargs["start_new_session"]))
        return Proc()

    envelope, code, _out, _err = _run_codex(
        "guarded prompt", tmp_path,
        preflight_fn=lambda *_args: _ready(), popen_impl=popen,
        platform_name="posix", signal_api=fake_signals,
    )
    labels = [event[0] for event in events]
    popen_index = labels.index("popen")
    communicate_index = labels.index("communicate")
    assert labels[0] == "mask"
    assert events[0][1] == fake_signals.SIG_BLOCK
    assert labels.count("handler") == 4  # install two, restore two
    assert all(labels.index(kind) < popen_index for kind in ("get", "handler"))
    assert next(i for i, event in enumerate(events)
                if event[0] == "mask" and event[1] == fake_signals.SIG_SETMASK) \
        < communicate_index
    assert events[popen_index] == ("popen", True)
    assert events[-1][0:2] == ("mask", fake_signals.SIG_SETMASK)
    assert code == 0
    assert envelope["model_receipt"]["tree_kill_verified"] is None


def test_posix_pending_termination_relays_only_after_pgid_is_persisted(
        tmp_path, monkeypatch):
    events = []
    fake_signals = _FakePosixSignals(events, deliver_pending=True)
    killed = []

    class Proc:
        pid = 777
        returncode = -9

        def communicate(self, input=None, timeout=None):
            events.append(("drain", input))
            return "", ""

    def verified_kill(proc, pgid, platform):
        killed.append((proc.pid, pgid, platform))
        return True

    monkeypatch.setattr(ca, "_kill_tree", verified_kill)
    envelope, code, _out, _err = _run_codex(
        "guarded prompt", tmp_path,
        preflight_fn=lambda *_args: _ready(),
        popen_impl=lambda *_args, **_kwargs: (
            events.append(("popen", True)) or Proc()),
        platform_name="posix", signal_api=fake_signals,
    )
    receipt = envelope["model_receipt"]
    assert events.index(("popen", True)) < events.index(("deliver", 15))
    assert killed and all(item == (777, 777, "posix") for item in killed)
    assert code == 130
    assert receipt["status"] == "aborted"
    assert receipt["aborted"] is True
    assert receipt["tree_kill_verified"] is True


def test_posix_popen_baseexception_restores_mask_without_exception_process_trust(
        tmp_path, monkeypatch):
    events = []
    fake_signals = _FakePosixSignals(events)

    class Child:
        pid = 909
        returncode = -9

        def communicate(self, input=None, timeout=None):
            events.append(("drain", timeout))
            return "", ""

    child = Child()

    class SpawnExit(SystemExit):
        def __init__(self):
            super().__init__(2)
            self.process = child

    monkeypatch.setattr(ca, "_kill_tree", lambda proc, pgid, platform: (
        events.append(("kill", proc.pid, pgid, platform)) or True))
    envelope, code, _out, _err = _run_codex(
        "work", tmp_path, preflight_fn=lambda *_args: _ready(),
        popen_impl=lambda *_args, **_kwargs: (_ for _ in ()).throw(SpawnExit()),
        platform_name="posix", signal_api=fake_signals,
    )
    receipt = envelope["model_receipt"]
    assert code == 130 and receipt["status"] == "spawn_aborted"
    assert not any(event[0] in ("kill", "drain") for event in events)
    assert events[-1][0:2] == ("mask", fake_signals.SIG_SETMASK)


def test_posix_partial_handler_install_systemexit_restores_original_mask(
        tmp_path):
    events = []

    class PartialInstall(_FakePosixSignals):
        def signal(self, sig, handler):
            if sig == self.SIGINT and not isinstance(handler, str):
                events.append(("install-failed", sig))
                raise SystemExit(9)
            super().signal(sig, handler)

    signals = PartialInstall(events)
    envelope, code, _out, _err = _run_codex(
        "work", tmp_path, preflight_fn=lambda *_args: _ready(),
        popen_impl=lambda *_args, **_kwargs: pytest.fail("must not spawn"),
        platform_name="posix", signal_api=signals,
    )
    assert code == 2
    assert envelope["model_receipt"]["status"] == "signal_guard_unavailable"
    assert events[-1][0:2] == ("mask", signals.SIG_SETMASK)
    assert any(event[0] == "install-failed" for event in events)


def test_guard_recheck_systemexit_restores_posix_signal_state(tmp_path):
    events = []
    signals = _FakePosixSignals(events)
    envelope, code, _out, _err = _run_codex(
        "work", tmp_path, preflight_fn=lambda *_args: _ready(),
        guard_recheck_fn=lambda *_args: (_ for _ in ()).throw(SystemExit(4)),
        popen_impl=lambda *_args, **_kwargs: pytest.fail("must not spawn"),
        platform_name="posix", signal_api=signals,
    )
    assert code == 2
    assert envelope["model_receipt"]["status"] == "runtime_guard_failed"
    assert events[-1][0:2] == ("mask", signals.SIG_SETMASK)


def test_signal_restore_baseexception_is_contained_and_fails_closed(tmp_path):
    events = []

    class RestoreFails(_FakePosixSignals):
        def signal(self, sig, handler):
            if isinstance(handler, str):
                events.append(("restore-failed", sig))
                raise SystemExit(3)
            super().signal(sig, handler)

    signals = RestoreFails(events)

    class Child:
        pid = 910
        returncode = 0

        def communicate(self, input=None, timeout=None):
            return _success_stream("done"), ""

    envelope, code, _out, _err = _run_codex(
        "work", tmp_path, preflight_fn=lambda *_args: _ready(),
        popen_impl=lambda *_args, **_kwargs: Child(),
        platform_name="posix", signal_api=signals,
    )
    assert code == 1
    assert envelope["model_receipt"]["status"] == "signal_guard_restore_failed"
    assert len([event for event in events if event[0] == "restore-failed"]) == 2
    assert events[-1][0:2] == ("mask", signals.SIG_SETMASK)


def test_guard_close_baseexception_after_popen_kills_suspended_child(tmp_path):
    events = []

    class Guard:
        def close(self):
            events.append("guard-close")
            raise SystemExit(6)

    class Job(_FakeWindowsJob):
        def abort_suspended(self, proc):
            events.append("abort-suspended")
            self.process_handle_verified = True
            self.empty_verified = True
            proc.returncode = -9
            return True

        def close(self):
            events.append("job-close")
            super().close()

    class Child:
        pid = 911
        returncode = None

        def communicate(self, input=None, timeout=None):
            events.append("drain")
            return "", ""

        def poll(self):
            return self.returncode

    def recheck(*_args):
        return {
            "ok": True, "config_guard_verified": True,
            "runtime_guard_rechecked": True,
            "executable_provenance_verified": True,
            "signer_image_binding_verified": True,
            "user_config_ignored": True, "mcp_entries_absent": True,
            "_executable_guard_handle": Guard(),
        }

    envelope, code, _out, _err = _run_codex(
        "work", tmp_path, preflight_fn=lambda *_args: _ready(),
        guard_recheck_fn=recheck,
        popen_impl=lambda *_args, **_kwargs: Child(),
        platform_name="nt", windows_job_factory=Job,
    )
    receipt = envelope["model_receipt"]
    assert code == 2 and receipt["status"] == "spawn_error"
    assert events == ["guard-close", "abort-suspended", "drain", "job-close"]
    assert receipt["seat_started"] is False
    assert receipt["tree_kill_verified"] is True
    assert receipt["output_drain_verified"] is True


def test_windows_job_factory_systemexit_restores_handlers_before_refusal(tmp_path):
    events = []

    class Signals:
        SIGTERM = 15
        SIGINT = 2

        def getsignal(self, signum):
            events.append(("get", signum))
            return "old-%s" % signum

        def signal(self, signum, handler):
            events.append(("signal", signum, handler))

    envelope, code, _out, _err = _run_codex(
        "work", tmp_path, preflight_fn=lambda *_args: _ready(),
        popen_impl=lambda *_args, **_kwargs: pytest.fail("must not spawn"),
        platform_name="nt", signal_api=Signals(),
        windows_job_factory=lambda: (_ for _ in ()).throw(SystemExit(5)),
    )
    assert code == 2
    assert envelope["model_receipt"]["status"] == \
        "containment_assignment_failed"
    restored = [event for event in events
                if event[0] == "signal" and isinstance(event[2], str)]
    assert len(restored) == 2


def test_posix_signal_guard_unavailable_fails_before_seat_spawn(tmp_path):
    unavailable = SimpleNamespace(SIG_BLOCK=1, SIG_SETMASK=2, SIGTERM=15, SIGINT=2)

    def no_spawn(*_args, **_kwargs):
        raise AssertionError("seat must not spawn without the POSIX signal guard")

    envelope, code, native_out, native_err = _run_codex(
        "work", tmp_path, preflight_fn=lambda *_args: _ready(),
        popen_impl=no_spawn, platform_name="posix", signal_api=unavailable,
    )
    receipt = envelope["model_receipt"]
    assert code == 2 and native_out == native_err == ""
    assert receipt["status"] == "signal_guard_unavailable"
    assert receipt["seat_started"] is False
    assert receipt["tree_kill_verified"] is None


def _spawn_offline_binary_child(code):
    executable = str(Path(sys.executable).resolve())
    return subprocess.Popen(
        [executable, "-c", code], executable=executable,
        cwd=str(Path(executable).parent), stdin=subprocess.PIPE,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        env=ca.subscription_only_env({}), shell=False, close_fds=True,
        text=False,
        creationflags=(getattr(subprocess, "CREATE_NO_WINDOW", 0)
                       if os.name == "nt" else 0),
        start_new_session=(os.name != "nt"),
    )


def _direct_root_terminator(proc):
    def terminate():
        try:
            proc.kill()
        except (OSError, subprocess.SubprocessError):
            pass
        return ca._proc_dead(proc, timeout_seconds=3)
    return terminate


@pytest.mark.parametrize(
    ("stream", "code", "expected"),
    (
        ("stdout", "import sys;sys.stdout.buffer.write(b'x'*8192);sys.stdout.flush()",
         "stdout"),
        ("stderr", "import sys;sys.stderr.buffer.write(b'y'*8192);sys.stderr.flush()",
         "stderr"),
    ),
)
def test_bounded_exchange_closes_individual_stream_overflow(
        stream, code, expected):
    proc = _spawn_offline_binary_child(code)
    try:
        result = ca._bounded_pipe_exchange(
            proc, "prompt", 5, terminate_fn=_direct_root_terminator(proc),
            stdout_limit=256, stderr_limit=256, aggregate_limit=384,
            drain_timeout=1)
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait(timeout=5)
    assert result["overflow_kind"] == expected == stream
    assert result["output_limits_verified"] is False
    assert result["output_eof_verified"] is True
    assert result["output_drain_verified"] is True
    assert result["root_exit_verified"] is True
    assert len(result[stream].encode("utf-8")) <= 256


def test_bounded_exchange_closes_combined_output_limit_without_truncated_success():
    code = (
        "import sys;"
        "sys.stdout.buffer.write(b'o'*96);sys.stdout.flush();"
        "sys.stderr.buffer.write(b'e'*96);sys.stderr.flush()"
    )
    proc = _spawn_offline_binary_child(code)
    try:
        result = ca._bounded_pipe_exchange(
            proc, None, 5, terminate_fn=_direct_root_terminator(proc),
            stdout_limit=128, stderr_limit=128, aggregate_limit=128,
            drain_timeout=1)
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait(timeout=5)
    assert result["overflow_kind"] == "aggregate"
    assert result["output_limits_verified"] is False
    assert (len(result["stdout"].encode("utf-8")) +
            len(result["stderr"].encode("utf-8"))) <= 128
    assert result["output_drain_verified"] is True


def test_bounded_exchange_timeout_and_cancel_finish_active_drains():
    code = (
        "import sys,time;sys.stdout.write('started\\n');sys.stdout.flush();"
        "time.sleep(30)"
    )
    timed = _spawn_offline_binary_child(code)
    try:
        timeout_result = ca._bounded_pipe_exchange(
            timed, "prompt", 0.1, terminate_fn=_direct_root_terminator(timed),
            stdout_limit=4096, stderr_limit=4096, aggregate_limit=4096,
            drain_timeout=1)
    finally:
        if timed.poll() is None:
            timed.kill()
            timed.wait(timeout=5)
    assert timeout_result["timed_out"] is True
    assert timeout_result["termination_attempted"] is True
    assert timeout_result["output_drain_verified"] is True
    assert timeout_result["root_exit_verified"] is True
    assert timeout_result["stdin_close_verified"] is True

    cancelled = _spawn_offline_binary_child(code)
    cancel = threading.Event()
    timer = threading.Timer(0.1, cancel.set)
    timer.start()
    try:
        cancel_result = ca._bounded_pipe_exchange(
            cancelled, "prompt", 5,
            terminate_fn=_direct_root_terminator(cancelled),
            abort_requested=cancel.is_set,
            stdout_limit=4096, stderr_limit=4096, aggregate_limit=4096,
            drain_timeout=1)
    finally:
        timer.cancel()
        if cancelled.poll() is None:
            cancelled.kill()
            cancelled.wait(timeout=5)
    assert cancel_result["aborted"] is True
    assert cancel_result["termination_attempted"] is True
    assert cancel_result["output_drain_verified"] is True
    assert cancel_result["root_exit_verified"] is True
    assert cancel_result["stdin_close_verified"] is True


def test_bounded_exchange_never_claims_blocked_prompt_writer_stopped():
    release = threading.Event()
    closed = threading.Event()

    class BlockedStdin:
        def write(self, payload):
            release.wait(2)
            return len(payload)

        def flush(self):
            return None

        def close(self):
            closed.set()

        def fileno(self):
            raise OSError("synthetic descriptor is unavailable")

    class Proc:
        pid = 6300
        returncode = None
        stdin = BlockedStdin()
        stdout = io.BytesIO(b"")
        stderr = io.BytesIO(b"")

        def wait(self, timeout=None):
            self.returncode = 0
            return 0

        def poll(self):
            return self.returncode

    proc = Proc()
    try:
        result = ca._bounded_pipe_exchange(
            proc, "blocked prompt", 1, terminate_fn=lambda: True,
            stdout_limit=1024, stderr_limit=1024, aggregate_limit=1024,
            drain_timeout=0.01)
        assert result["output_drain_verified"] is True
        assert result["root_exit_verified"] is True
        assert result["stdin_write_verified"] is False
        assert result["stdin_close_verified"] is False
    finally:
        release.set()
    assert closed.wait(1)


def test_protocol_event_count_limit_fails_before_retaining_unbounded_events(
        monkeypatch):
    monkeypatch.setattr(ca, "MAX_NATIVE_EVENT_COUNT", 2)
    stream = "\n".join((
        json.dumps({"type": "thread.started", "thread_id": "one"}),
        json.dumps({"type": "item.completed", "item": {
            "type": "agent_message", "text": "must not succeed"}}),
        json.dumps({"type": "turn.completed", "usage": {}}),
    ))
    parsed = ca.parse_jsonl(stream)
    assert parsed["limits_exceeded"] is True
    assert parsed["event_count"] == 2
    assert parsed["ok"] is False
    assert ca.classify_failure("", parsed, 0) == "protocol_limit_exceeded"


def test_preflight_production_path_jobs_all_three_local_probes(tmp_path):
    jobs = []
    calls = []

    class Job(_FakeWindowsJob):
        def __init__(self):
            super().__init__()
            jobs.append(self)

        def verify_empty(self):
            self.empty_verified = True
            return True

    class Proc:
        def __init__(self, pid, stdout=b"", stderr=b""):
            self.pid = pid
            self.returncode = None
            self.stdin = None
            self.stdout = io.BytesIO(stdout)
            self.stderr = io.BytesIO(stderr)

        def wait(self, timeout=None):
            self.returncode = 0
            return 0

        def poll(self):
            return self.returncode

    def popen(argv, **kwargs):
        calls.append((list(argv), dict(kwargs)))
        assert kwargs["creationflags"] & ca._WindowsJob.CREATE_SUSPENDED
        assert kwargs["text"] is False
        if argv[1:] == ["--version"]:
            payload = b"codex-cli contained"
        elif argv[1:] == ["login", "status"]:
            payload = b"Logged in using ChatGPT"
        else:
            assert argv[-2:] == ["debug", "models"]
            payload = _catalog().encode("utf-8")
        return Proc(5000 + len(calls), payload)

    executable = str((tmp_path / "codex.exe").resolve())
    result = ca.preflight_codex(
        executable, provenance_fn=lambda cmd, _env: {
            "ok": True, "executable_path": cmd,
            "executable_fingerprint": {
                "path": cmd, "exists": True, "sha256": "f" * 64},
            "executable_provenance_verified": True,
            "signer_image_binding_verified": True,
        }, popen_impl=popen, platform_name="nt", windows_job_factory=Job)
    assert result["ok"] is True
    assert result["preflight_probe_count"] == 3
    assert result["preflight_containment_kind"] == "windows_job"
    assert result["preflight_complete_tree_containment"] is True
    assert result["preflight_no_inference_verified"] is True
    assert result["preflight_no_network_intent_verified"] is True
    assert result["preflight_output_limits_verified"] is True
    assert result["preflight_output_drain_verified"] is True
    assert result["preflight_root_exit_verified"] is True
    assert all(job.closed for job in jobs) and len(jobs) == len(calls) == 3


def test_preflight_timeout_proves_windows_job_root_and_pipe_cleanup(tmp_path):
    created = []

    class Job(_FakeWindowsJob):
        def __init__(self):
            super().__init__()
            created.append(self)

        def terminate_verified(self, proc, timeout_seconds=5.0):
            proc.returncode = -9
            self.empty_verified = True
            return True

    class Proc:
        pid = 6100
        returncode = None
        stdin = None
        stdout = io.BytesIO(b"")
        stderr = io.BytesIO(b"")

        def wait(self, timeout=None):
            if self.returncode is None:
                raise subprocess.TimeoutExpired("probe", timeout)
            return self.returncode

        def poll(self):
            return self.returncode

    executable = str((tmp_path / "codex.exe").resolve())
    result = ca._run_preflight_probe(
        executable, ("--version",), ca.subscription_only_env({}), 0.01,
        popen_impl=lambda *_args, **_kwargs: Proc(), platform_name="nt",
        windows_job_factory=Job)
    evidence = result["evidence"]
    assert result["ok"] is False
    assert result["status"] == "preflight_timeout"
    assert evidence["preflight_output_drain_verified"] is True
    assert evidence["preflight_root_exit_verified"] is True
    assert evidence["preflight_windows_job_empty_verified"] is True
    assert created[0].closed is True


def test_posix_preflight_containment_is_explicitly_degraded(
        tmp_path, monkeypatch):
    class Proc:
        pid = 6200
        returncode = None
        stdin = None
        stdout = io.BytesIO(b"codex-cli posix")
        stderr = io.BytesIO(b"")

        def wait(self, timeout=None):
            self.returncode = 0
            return 0

        def poll(self):
            return self.returncode

    monkeypatch.setattr(ca, "_minimal_env_verified", lambda *_args: True)
    executable = str((tmp_path / "codex").resolve())
    result = ca._run_preflight_probe(
        executable, ("--version",), {}, 1,
        popen_impl=lambda *_args, **_kwargs: Proc(), platform_name="posix")
    assert result["ok"] is True
    evidence = result["evidence"]
    assert evidence["preflight_containment_kind"] == \
        "posix_process_group_degraded"
    assert evidence["preflight_complete_tree_containment"] is False
    assert evidence["preflight_windows_job_policy_verified"] is False


@pytest.mark.skipif(os.name != "nt", reason="real Windows bounded-seat canary")
def test_paid_seat_stdout_overflow_returns_closed_status_and_bounded_receipt(
        tmp_path, monkeypatch):
    monkeypatch.setattr(ca, "MAX_NATIVE_STDOUT_BYTES", 256)
    monkeypatch.setattr(ca, "MAX_NATIVE_STDERR_BYTES", 256)
    monkeypatch.setattr(ca, "MAX_NATIVE_OUTPUT_BYTES", 384)
    executable = str(Path(sys.executable).resolve())
    code = (
        "import sys;sys.stdin.buffer.read();"
        "sys.stdout.buffer.write(b'x'*8192);sys.stdout.flush()"
    )

    def popen(_argv, **kwargs):
        return subprocess.Popen(
            [executable, "-c", code], executable=executable,
            cwd=str(Path(executable).parent), stdin=subprocess.PIPE,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            env=ca.subscription_only_env({}), shell=False, close_fds=True,
            text=False, creationflags=kwargs["creationflags"])

    envelope, adapter_exit, _native_out, _native_err = _run_codex(
        "bounded prompt", tmp_path,
        preflight_fn=lambda *_args: _ready(), popen_impl=popen,
        platform_name="nt", windows_job_factory=ca._WindowsJob)
    receipt = envelope["model_receipt"]
    assert adapter_exit == 1 and envelope["is_error"] is True
    assert receipt["status"] == "output_limit_exceeded"
    assert receipt["output_overflow_kind"] == "stdout"
    assert receipt["output_limits_verified"] is False
    assert receipt["output_eof_verified"] is True
    assert receipt["output_drain_verified"] is True
    assert receipt["native_stdout_bytes"] > ca.MAX_NATIVE_STDOUT_BYTES
    assert receipt["seat_started"] is True


@pytest.mark.skipif(os.name != "nt", reason="real Windows preflight Job canary")
def test_real_offline_windows_preflight_probe_is_suspended_owned_and_drained():
    executable = str(Path(sys.executable).resolve())
    result = ca._run_preflight_probe(
        executable, ("--version",), ca.subscription_only_env({}), 15)
    assert result["ok"] is True, result
    evidence = result["evidence"]
    assert evidence["preflight_no_inference_verified"] is True
    assert evidence["preflight_no_network_intent_verified"] is True
    assert evidence["preflight_complete_tree_containment"] is True
    assert evidence["preflight_windows_job_policy_verified"] is True
    assert evidence["preflight_windows_job_assignment_verified"] is True
    assert evidence["preflight_windows_job_membership_verified"] is True
    assert evidence["preflight_windows_process_handle_verified"] is True
    assert evidence["preflight_windows_primary_thread_verified"] is True
    assert evidence["preflight_windows_process_resumed"] is True
    assert evidence["preflight_windows_job_empty_verified"] is True
    assert evidence["preflight_output_drain_verified"] is True
    assert evidence["preflight_root_exit_verified"] is True


@pytest.mark.skipif(os.name != "nt", reason="real Windows descendant/pipe canary")
def test_windows_job_terminates_descendant_holding_native_pipe_open():
    executable = str(Path(sys.executable).resolve())
    code = (
        "import subprocess,sys;"
        "subprocess.Popen([sys.executable,'-c','import time;time.sleep(30)']);"
        "print('root-exit', flush=True)"
    )
    creationflags = (
        ca._WindowsJob.CREATE_SUSPENDED |
        getattr(subprocess, "CREATE_NO_WINDOW", 0))
    job = ca._WindowsJob()
    proc = None
    try:
        proc = subprocess.Popen(
            [executable, "-c", code], executable=executable,
            cwd=str(Path(executable).parent), stdin=subprocess.PIPE,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            env=ca.subscription_only_env({}), shell=False, close_fds=True,
            text=False, creationflags=creationflags)
        assert job.assign_and_resume(proc) is True
        result = ca._bounded_pipe_exchange(
            proc, "prompt", 5,
            terminate_fn=lambda: job.terminate_verified(proc),
            stdout_limit=4096, stderr_limit=4096, aggregate_limit=4096,
            drain_timeout=0.25)
        assert result["termination_attempted"] is True
        assert result["termination_verified"] is True
        assert result["output_eof_verified"] is True
        assert result["output_drain_verified"] is True
        assert result["root_exit_verified"] is True
        assert job.verify_empty() is True
    finally:
        if proc is not None and proc.poll() is None:
            job.terminate_verified(proc)
            proc.wait(timeout=5)
        job.close()


def test_installed_cli_parses_full_override_set_without_starting_model(tmp_path):
    try:
        executable = Path(ca.resolve_codex_cmd({})).resolve()
    except FileNotFoundError:
        pytest.skip("installed Codex binary is unavailable")
    clean_env = ca.subscription_only_env({})
    common = dict(
        cwd=str(executable.parent), executable=str(executable),
        stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
        stderr=subprocess.PIPE, env=clean_env, shell=False, close_fds=True,
        text=True, encoding="utf-8", errors="replace", timeout=30,
        creationflags=(getattr(subprocess, "CREATE_NO_WINDOW", 0)
                       if os.name == "nt" else 0),
    )
    help_result = subprocess.run(
        [str(executable), "exec", "--help"], **common)
    assert help_result.returncode == 0, help_result.stderr or help_result.stdout
    help_text = "%s\n%s" % (help_result.stdout, help_result.stderr)
    assert "--ignore-user-config" in help_text
    assert "do not load" in help_text.casefold()
    assert "config.toml" in help_text.casefold()
    odd_target = tmp_path / "dotted.path spaces 雪"
    odd_target.mkdir()
    project_config = odd_target / ".codex"
    project_config.mkdir()
    sentinel = "ANCHOR_PROJECT_CONFIG_MUST_NOT_LOAD_7E91"
    (project_config / "config.toml").write_text(
        'developer_instructions = "%s"\n' % sentinel, encoding="utf-8")
    generated = ca.build_exec_argv(str(executable), odd_target)
    complete_help = subprocess.run(generated[:-1] + ["--help"], **common)
    assert complete_help.returncode == 0, \
        complete_help.stderr or complete_help.stdout
    assert "--ignore-user-config" in complete_help.stdout
    config_args = []
    for index, value in enumerate(generated[:-1]):
        if value == "-c":
            config_args.extend(("-c", generated[index + 1]))
    result = subprocess.run(
        [str(executable), *config_args, "debug", "prompt-input"],
        **common,
    )
    assert result.returncode == 0, result.stderr or result.stdout
    assert sentinel not in result.stdout
    assert sentinel not in result.stderr
