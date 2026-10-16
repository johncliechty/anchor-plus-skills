"""Synthetic service gates: no Jupyter process, account creation, or installation."""
from copy import deepcopy
import json
import os
from pathlib import Path

import pytest

import notebook_service as service


HASH = "argon2:$argon2id$v=19$m=10240,t=10,p=8$c3ludGhldGljc2FsdA$c3ludGhldGljaGFzaA"
ACCOUNT = {"account": "SYNTHETIC\\NotebookRunner", "sid": "S-1-5-21-100-100-100-1010",
           "platform": "nt", "is_admin": False}


@pytest.fixture
def setup(tmp_path):
    root = tmp_path / "notebooks"
    private = tmp_path / "private-service"
    root.mkdir()
    private.mkdir()
    python = tmp_path / "python.exe"
    r = tmp_path / "R.exe"
    python.write_bytes(b"synthetic, never executed")
    r.write_bytes(b"synthetic, never executed")
    password = private / "jupyter_server_config.json"
    password.write_text(json.dumps({"IdentityProvider": {"hashed_password": HASH}}), encoding="utf-8")
    runtime = {"schema_version": 1, "enabled": True, "public_base_url": "https://notebooks.example.test/",
               "root_dir": str(root), "execution_host": "SYNTHETIC",
               "local_kernel_specs": {
                   "python3": [str(python), "-m", "ipykernel_launcher", "-f", "{connection_file}"],
                   "ir": [str(r), "--slave", "-e", "IRkernel::main()", "--args", "{connection_file}"]}}
    options = {"runtime_dir": str(private), "password_file": str(password),
               "service_account": ACCOUNT["account"], "dedicated_account_confirmed": True,
               "port": 8891}
    return runtime, options


def plan_for(setup, **kwargs):
    runtime, options = setup
    return service.build_launch_plan(runtime, options, account_probe=lambda: deepcopy(ACCOUNT),
        private_path_check=lambda path, account: None, runtime_validator=deepcopy,
        environ={"SYSTEMROOT": "C:\\Windows", "XAI_API_KEY": "never-forward", "JUPYTER_GATEWAY_URL": "https://remote.invalid"},
        **kwargs)


def test_plan_read_only_no_secret_values_or_creation(setup):
    runtime, options = setup
    private = Path(options["runtime_dir"])
    before = sorted(p.name for p in private.iterdir())
    plan = plan_for(setup)
    assert sorted(p.name for p in private.iterdir()) == before
    serialized = json.dumps(plan)
    assert HASH not in serialized
    assert "never-forward" not in serialized
    assert "https://remote.invalid" not in serialized
    assert plan["execution_host"] == "SYNTHETIC"
    assert plan["listen_host"] == "127.0.0.1"
    assert plan["port"] == 8891


def test_windows_process_floor_is_explicit_and_does_not_restore_credentials(setup):
    environment = plan_for(setup)["environment"]
    service.validate_process_environment(environment)
    assert environment["WINDIR"] == environment["SYSTEMROOT"]
    assert environment["PATHEXT"] == ".COM;.EXE;.BAT;.CMD"
    assert "XAI_API_KEY" not in environment
    assert "JUPYTER_GATEWAY_URL" not in environment


@pytest.mark.parametrize("missing", ["SYSTEMROOT", "WINDIR", "PATHEXT", "PATH", "TEMP", "TMP"])
def test_missing_windows_floor_fails_before_environment_mutation_or_import(setup, missing):
    plan = plan_for(setup)
    del plan["environment"][missing]
    before = dict(os.environ)
    with pytest.raises(service.NotebookServiceError) as error:
        service.run_jupyter(plan, HASH)
    assert error.value.code == "windows_environment_incomplete"
    assert dict(os.environ) == before


def test_forwarded_headers_not_trusted_and_fail_is_a_normal_exception(setup):
    assert service.jupyter_config(plan_for(setup), HASH)["ServerApp"]["trust_xheaders"] is False
    with pytest.raises(ValueError) as error:
        service._fail("synthetic_request", "synthetic request error")
    assert not isinstance(error.value, SystemExit)


@pytest.mark.parametrize("changes,code", [
    ({"dedicated_account_confirmed": False}, "dedicated_account_required"),
    ({"service_account": "someone"}, "dedicated_account_required"),
    ({"service_account": "SYNTHETIC\\Other"}, "wrong_service_account"),
    ({"listen_host": "0.0.0.0"}, "loopback_required"),
    ({"listen_host": "localhost"}, "loopback_required"),
    ({"port": 0}, "invalid_port"),
    ({"port": True}, "invalid_port"),
    ({"token": "secret"}, "invalid_service_options"),
])
def test_invalid_deployment_options_fail_closed(setup, changes, code):
    setup[1].update(changes)
    with pytest.raises(service.NotebookServiceError) as error:
        plan_for(setup)
    assert error.value.code == code


def test_account_token_rejects_admin_including_filtered_tokens(setup):
    account = dict(ACCOUNT, is_admin=True)
    with pytest.raises(service.NotebookServiceError) as error:
        service.build_launch_plan(*setup, account_probe=lambda: account, runtime_validator=deepcopy,
                                  private_path_check=lambda *_: None)
    assert error.value.code == "administrator_account_forbidden"


def test_account_probe_failure_is_not_replaced_with_environment_identity(setup):
    with pytest.raises(service.NotebookServiceError) as error:
        service.build_launch_plan(*setup, account_probe=lambda: {"account": ACCOUNT["account"]},
                                  runtime_validator=deepcopy, private_path_check=lambda *_: None)
    assert error.value.code == "security_probe_failed"


def test_acl_failure_is_not_repaired_or_ignored(setup):
    checked = []

    def reject(path, account):
        checked.append(path)
        raise service.NotebookServiceError("private_directory_required", "Synthetic public DACL")

    with pytest.raises(service.NotebookServiceError, match="Synthetic"):
        service.build_launch_plan(*setup, account_probe=lambda: ACCOUNT,
                                  runtime_validator=deepcopy, private_path_check=reject)
    assert checked == [Path(setup[1]["runtime_dir"])]


def test_private_state_cannot_be_served_as_notebook_files(setup):
    runtime, options = setup
    runtime["root_dir"] = str(Path(options["runtime_dir"]).parent)
    with pytest.raises(service.NotebookServiceError) as error:
        plan_for(setup)
    assert error.value.code == "runtime_tree_overlap"


def test_password_file_must_be_private_and_jupyter_generated(setup, tmp_path):
    runtime, options = setup
    external = tmp_path / "outside-password.json"
    external.write_text("{}", encoding="utf-8")
    options["password_file"] = str(external)
    with pytest.raises(service.NotebookServiceError) as error:
        plan_for(setup)
    assert error.value.code == "password_file_location"


@pytest.mark.parametrize("document", [
    {"PasswordIdentityProvider": {"hashed_password": "plaintext"}},
    {"IdentityProvider": {"hashed_password": "sha1:old:weak"}},
    {"IdentityProvider": {"token": "placeholder"}},
    {"IdentityProvider": {"hashed_password": HASH}, "PasswordIdentityProvider": {"hashed_password": HASH + "x"}},
    [],
])
def test_reject_plaintext_weak_or_conflicting_password_configuration(setup, document):
    path = Path(setup[1]["password_file"])
    path.write_text(json.dumps(document), encoding="utf-8")
    with pytest.raises(service.NotebookServiceError) as error:
        plan_for(setup)
    assert error.value.code == "password_setup_required"
    assert HASH not in str(error.value)


def test_jupyter_password_section_variants_accepted(setup):
    path = Path(setup[1]["password_file"])
    for section in ("IdentityProvider", "PasswordIdentityProvider"):
        path.write_text(json.dumps({section: {"hashed_password": HASH}}), encoding="utf-8")
        assert service.read_password_hash(path) == HASH


def test_runtime_validator_not_replaced_with_a_weaker_service_copy(setup):
    def rejected(runtime):
        raise ValueError("synthetic remote kernel rejected by shared validator")

    with pytest.raises(ValueError, match="shared validator"):
        service.build_launch_plan(*setup, runtime_validator=rejected)


def test_environment_is_allowlisted_not_a_provider_credential_denylist(setup):
    plan = plan_for(setup)
    inherited = {"SYSTEMROOT": "C:\\Windows", "PATH": "sensitive-other-provider-tools",
        "ANTHROPIC_API_KEY": "secret", "OPENAI_API_KEY": "secret", "XAI_API_KEY": "secret",
        "FUTURE_AI_CREDENTIAL": "secret", "ANCHOR_TOKEN": "secret", "PYTHONPATH": "hijack",
        "JUPYTER_GATEWAY_URL": "remote", "JUPYTER_CONFIG_PATH": "override",
        "JUPYTER_PATH": "remote-specs", "JUPYTER_KERNEL_PROVISIONER_NAME": "remote",
        "R_LIBS_USER": "unapproved-library", "R_PROFILE_USER": "unapproved-startup"}
    environment = service.build_environment(plan, inherited)
    rendered = json.dumps(environment)
    for forbidden in ("secret", "sensitive-other-provider-tools", "hijack", "unapproved", "remote-specs"):
        assert forbidden not in rendered
    assert "JUPYTER_GATEWAY_URL" not in environment
    assert "JUPYTER_CONFIG_PATH" not in environment
    assert environment["PYTHONNOUSERSITE"] == "1"
    assert environment["USERPROFILE"] == plan["directories"]["profile"]


def test_prepare_writes_only_declared_local_kernels_and_is_idempotent(setup):
    plan = plan_for(setup)
    checked = []
    checker = lambda path, account: checked.append(str(path))
    service.prepare_runtime(plan, private_path_check=checker)
    service.prepare_runtime(plan, private_path_check=checker)
    kernel_root = Path(plan["directories"]["data"]) / "kernels"
    assert {path.name for path in kernel_root.iterdir()} == {"python3", "ir"}
    for name, expected in plan["kernels"].items():
        actual = json.loads((kernel_root / name / "kernel.json").read_text(encoding="utf-8"))
        assert actual == expected
        assert actual["metadata"]["kernel_provisioner"]["provisioner_name"] == "local-provisioner"
        assert actual["env"] == {}
    assert not list(Path(setup[0]["root_dir"]).iterdir())
    assert checked


def test_prepare_never_overwrites_a_changed_kernelspec(setup):
    plan = plan_for(setup)
    service.prepare_runtime(plan, private_path_check=lambda *_: None)
    path = Path(plan["directories"]["data"]) / "kernels" / "python3" / "kernel.json"
    path.write_text("changed by collaborator", encoding="utf-8")
    with pytest.raises(service.NotebookServiceError) as error:
        service.prepare_runtime(plan, private_path_check=lambda *_: None)
    assert error.value.code == "managed_file_conflict"
    assert path.read_text(encoding="utf-8") == "changed by collaborator"


def test_python_only_runtime_supported(setup):
    del setup[0]["local_kernel_specs"]["ir"]
    assert set(plan_for(setup)["kernels"]) == {"python3"}


def test_config_has_password_not_token_and_explicit_local_restrictions(setup):
    plan = plan_for(setup)
    config = service.jupyter_config(plan, HASH)
    assert config["IdentityProvider"]["token"] == ""
    assert config["PasswordIdentityProvider"]["password_required"] is True
    assert config["PasswordIdentityProvider"]["hashed_password"] == HASH
    app = config["ServerApp"]
    assert app["port_retries"] == 0
    assert app["ip"] == "127.0.0.1"
    assert app["disable_check_xsrf"] is False
    assert app["allow_unauthenticated_access"] is False
    assert app["allow_external_kernels"] is False
    assert app["allow_remote_access"] is False
    assert "notebooks.example.test" in app["local_hostnames"]
    assert app["shutdown_no_activity_timeout"] == 0
    assert app["jpserver_extensions"] == {"jupyterlab": True}
    assert config["GatewayClient"]["url"] == ""
    assert config["KernelSpecManager"]["ensure_native_kernel"] is False


def test_unsafe_link_is_rejected_before_read_or_write(setup, tmp_path):
    target = tmp_path / "other"
    target.mkdir()
    link = Path(setup[1]["runtime_dir"]) / "config"
    try:
        link.symlink_to(target, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("Symlink creation unavailable for this test account")
    plan = plan_for(setup)
    with pytest.raises(service.NotebookServiceError) as error:
        service.prepare_runtime(plan, private_path_check=lambda *_: None)
    assert error.value.code == "reparse_path"
    assert not list(target.iterdir())
