"""Portable contract tests: no Jupyter process, kernel, or executable is run."""

import copy
import json
import socket
from pathlib import Path

import pytest

from notebook_runtime import (
    NotebookRuntimeError,
    notebook_url,
    runtime_probe_code,
    runtime_status,
    validate_config,
)


@pytest.fixture
def runtime(tmp_path):
    root = tmp_path / "workspace"
    project = root / "Example Project"
    project.mkdir(parents=True)
    python = tmp_path / "python.exe"
    python.write_text("not an executable; never run", encoding="utf-8")
    r = tmp_path / "R.exe"
    r.write_text("not an executable; never run", encoding="utf-8")
    notebook = project / "Lesson 1.ipynb"
    notebook.write_text('{"cells": [], "nbformat": 4}', encoding="utf-8")
    config = {
        "schema_version": 1,
        "enabled": True,
        "public_base_url": "https://notebooks.example.test:8446/jupyter/",
        "root_dir": str(root),
        "execution_host": socket.gethostname(),
        "local_kernel_specs": {
            "python3": [str(python), "-m", "ipykernel_launcher", "-f", "{connection_file}"],
            "ir": [str(r), "--slave", "-e", "IRkernel::main()", "--args", "{connection_file}"],
        },
    }
    return config, project, notebook


def test_normalizes_without_mutation_and_maps_root(runtime):
    config, project, _ = runtime
    before = copy.deepcopy(config)
    result = validate_config(config)
    assert result["public_base_url"] == "https://notebooks.example.test:8446/jupyter"
    assert result["root_dir"] == str(Path(config["root_dir"]).resolve())
    assert config == before
    assert notebook_url(config, project, "Lesson 1.ipynb") == (
        "https://notebooks.example.test:8446/jupyter/lab/tree/Example%20Project/Lesson%201.ipynb"
    )


def test_url_encodes_notebook_segments_exactly_once(runtime):
    config, project, _ = runtime
    name = "café 100% #1.ipynb"
    (project / name).write_text("{}", encoding="utf-8")
    result = notebook_url(config, project, name)
    assert result.endswith("/caf%C3%A9%20100%25%20%231.ipynb")
    assert "?" not in result and "#" not in result


@pytest.mark.parametrize("url", [
    "https://user:secret@example.com", "https://user@example.com",
    "https://example.test/?token=private", "https://example.test/?",
    "https://example.test/#private", "https://example.test/#",
    "https://example.test\\@evil.test", "https://example.test/\nprivate",
    "https://example.test/%2e%2e", "https://example.test/%252e%252e",
    "https://example.test/%2fprivate", "https://example.test//prefix",
    "https://example.test:70000", "https://[broken", "https:///missing-host",
    "javascript:alert(1)", "https://bad_host.test", "https://example.test/%FF",
    "https://[::1%25eth0]",
])
def test_rejects_hostile_public_urls_without_echoing(runtime, url):
    config, _, _ = runtime
    config["public_base_url"] = url
    with pytest.raises(NotebookRuntimeError) as caught:
        validate_config(config)
    assert url not in str(caught.value)
    assert "secret" not in json.dumps(runtime_status(config))


@pytest.mark.parametrize("url", ["http://localhost:8890", "http://127.0.0.1:8890", "http://[::1]:8890"])
def test_http_requires_explicit_loopback_development(runtime, url):
    config, _, _ = runtime
    config["public_base_url"] = url
    with pytest.raises(NotebookRuntimeError, match="HTTPS"):
        validate_config(config)
    config["allow_loopback_dev"] = True
    assert validate_config(config)["public_base_url"] == url


@pytest.mark.parametrize("url", ["http://example.test", "http://192.168.1.2", "http://localhost.evil.test", "http://2130706433"])
def test_loopback_override_never_enables_remote_http(runtime, url):
    config, _, _ = runtime
    config.update(public_base_url=url, allow_loopback_dev=True)
    with pytest.raises(NotebookRuntimeError):
        validate_config(config)


@pytest.mark.parametrize("name", [
    "../Lesson 1.ipynb", "nested/../../Lesson 1.ipynb", "/Lesson 1.ipynb",
    "C:\\Lesson 1.ipynb", "C:Lesson 1.ipynb", "\\\\server\\share\\test.ipynb",
    "\\Lesson 1.ipynb", "nested//test.ipynb", "./Lesson 1.ipynb",
    "nested/../Lesson 1.ipynb", "nested./test.ipynb", "nested /test.ipynb",
    "CON.ipynb", "nested:stream/test.ipynb", "lesson.py", "lesson.ipynb:stream",
    "bad\x00.ipynb",
])
def test_rejects_traversal_absolute_and_ambiguous_notebook_paths(runtime, name):
    config, project, _ = runtime
    with pytest.raises(NotebookRuntimeError) as caught:
        notebook_url(config, project, name)
    assert caught.value.code == "invalid_notebook_path"


def test_accepts_portable_windows_relative_separators(runtime):
    config, project, _ = runtime
    nested = project / "nested"
    nested.mkdir()
    (nested / "test.ipynb").write_text("{}", encoding="utf-8")
    assert notebook_url(config, project, "nested\\test.ipynb").endswith("/nested/test.ipynb")


def test_missing_notebook_directory_and_outside_project_are_rejected(runtime, tmp_path):
    config, project, _ = runtime
    with pytest.raises(NotebookRuntimeError) as caught:
        notebook_url(config, project, "missing.ipynb")
    assert caught.value.code == "notebook_unavailable"
    (project / "directory.ipynb").mkdir()
    with pytest.raises(NotebookRuntimeError):
        notebook_url(config, project, "directory.ipynb")
    elsewhere = tmp_path / "outside"
    elsewhere.mkdir()
    (elsewhere / "test.ipynb").write_text("{}", encoding="utf-8")
    with pytest.raises(NotebookRuntimeError) as caught:
        notebook_url(config, elsewhere, "test.ipynb")
    assert caught.value.code == "project_outside_root"


def _symlink_or_skip(link, target, *, directory=False):
    try:
        link.symlink_to(target, target_is_directory=directory)
    except (OSError, NotImplementedError):
        pytest.skip("Creating symlinks requires unavailable platform permissions")


def test_notebook_symlink_escape_rejected(runtime, tmp_path):
    config, project, _ = runtime
    outside = tmp_path / "outside.ipynb"
    outside.write_text("{}", encoding="utf-8")
    _symlink_or_skip(project / "escape.ipynb", outside)
    with pytest.raises(NotebookRuntimeError) as caught:
        notebook_url(config, project, "escape.ipynb")
    assert caught.value.code == "notebook_outside_root"


def test_symlink_to_other_project_within_jupyter_root_is_rejected(runtime):
    config, project, _ = runtime
    other_project = project.parent / "Other Project"
    other_project.mkdir()
    other = other_project / "other.ipynb"
    other.write_text("{}", encoding="utf-8")
    _symlink_or_skip(project / "escape.ipynb", other)
    with pytest.raises(NotebookRuntimeError) as caught:
        notebook_url(config, project, "escape.ipynb")
    assert caught.value.code == "notebook_outside_root"


def test_directory_symlink_escape_rejected(runtime, tmp_path):
    config, project, _ = runtime
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "test.ipynb").write_text("{}", encoding="utf-8")
    _symlink_or_skip(project / "linked", outside, directory=True)
    with pytest.raises(NotebookRuntimeError):
        notebook_url(config, project, "linked/test.ipynb")


def test_symlink_inside_project_maps_to_canonical_file(runtime):
    config, project, notebook = runtime
    _symlink_or_skip(project / "alias.ipynb", notebook)
    assert notebook_url(config, project, "alias.ipynb").endswith("/Lesson%201.ipynb")


def test_notebook_symlink_cannot_disguise_a_nonnotebook_file(runtime):
    config, project, _ = runtime
    text_file = project / "notes.txt"
    text_file.write_text("not a notebook", encoding="utf-8")
    _symlink_or_skip(project / "alias.ipynb", text_file)
    with pytest.raises(NotebookRuntimeError) as caught:
        notebook_url(config, project, "alias.ipynb")
    assert caught.value.code == "invalid_notebook_path"


@pytest.mark.parametrize("field,value", [
    ("gateway_url", "https://remote.invalid"),
    ("environment", {"JUPYTER_GATEWAY_URL": "https://remote.invalid"}),
    ("kernel_provisioner", "remote-provisioner"),
    ("GatewayClient", {"url": "https://remote.invalid"}),
    ("token", "private-secret"),
])
def test_rejects_remote_gateway_provisioner_and_token_fields(runtime, field, value):
    config, _, _ = runtime
    config[field] = value
    with pytest.raises(NotebookRuntimeError) as caught:
        validate_config(config)
    assert caught.value.code == "unsupported_config"
    assert "private-secret" not in json.dumps(runtime_status(config))


@pytest.mark.parametrize("argv", [
    ["python", "-m", "ipykernel_launcher", "-f", "{connection_file}"],
    ["ssh", "host", "{connection_file}"],
    {"argv": ["python"], "metadata": {"kernel_provisioner": {"provisioner_name": "remote"}}},
    [],
])
def test_rejects_nonlocal_or_nonargv_kernel_specs(runtime, argv):
    config, _, _ = runtime
    config["local_kernel_specs"]["python3"] = argv
    with pytest.raises(NotebookRuntimeError):
        validate_config(config)


def test_existing_remote_launcher_and_arbitrary_python_code_are_rejected(runtime, tmp_path):
    config, _, _ = runtime
    ssh = tmp_path / "ssh.exe"
    ssh.write_text("never run", encoding="utf-8")
    config["local_kernel_specs"]["python3"] = [str(ssh), "host", "{connection_file}"]
    with pytest.raises(NotebookRuntimeError):
        validate_config(config)
    config["local_kernel_specs"]["python3"] = [str(tmp_path / "python.exe"), "-c", "import os", "{connection_file}"]
    with pytest.raises(NotebookRuntimeError):
        validate_config(config)


def test_requires_connection_marker_and_direct_r_entry_point(runtime):
    config, _, _ = runtime
    config["local_kernel_specs"]["ir"][-1] = "connection.json"
    with pytest.raises(NotebookRuntimeError):
        validate_config(config)
    config["local_kernel_specs"]["ir"][-1] = "{connection_file}"
    config["local_kernel_specs"]["ir"][3] = "system('remote-launcher')"
    with pytest.raises(NotebookRuntimeError):
        validate_config(config)


def test_missing_optional_r_does_not_block_python(runtime):
    config, _, _ = runtime
    del config["local_kernel_specs"]["ir"]
    assert runtime_status(config)["kernels"] == ["python3"]


def test_host_is_this_anchor_machine_and_never_claims_probe_attestation(runtime):
    config, _, _ = runtime
    assert runtime_status(config)["host_attested"] is False
    config["execution_host"] = "not-this-host.invalid"
    with pytest.raises(NotebookRuntimeError) as caught:
        validate_config(config)
    assert caught.value.code == "host_mismatch"


def test_status_is_generic_and_paths_are_opt_in(runtime):
    config, _, _ = runtime
    status = runtime_status(config)
    assert status["authentication"] == "jupyter_login_required"
    assert "root_dir" not in status and "public_base_url" not in status
    assert "local_kernel_specs" not in status
    assert "not an OS sandbox" in status["security_notice"]
    assert runtime_status(config, include_paths=True)["root_dir"] == str(Path(config["root_dir"]).resolve())
    assert runtime_status(None)["status"] == "not_configured"


def test_disabled_config_never_yields_live_url(runtime):
    config, project, _ = runtime
    config["enabled"] = False
    assert runtime_status(config)["status"] == "disabled"
    with pytest.raises(NotebookRuntimeError) as caught:
        notebook_url(config, project, "Lesson 1.ipynb")
    assert caught.value.code == "disabled"


def test_schema_alias_and_strict_boolean_fields(runtime):
    config, _, _ = runtime
    config["schema"] = config.pop("schema_version")
    assert validate_config(config)["schema_version"] == 1
    config["schema_version"] = 2
    with pytest.raises(NotebookRuntimeError):
        validate_config(config)
    config["schema_version"] = 1
    config["enabled"] = "true"
    with pytest.raises(NotebookRuntimeError):
        validate_config(config)


def test_probe_code_is_explicit_small_and_not_executed():
    python = runtime_probe_code("python")
    r = runtime_probe_code("R")
    assert "socket.gethostname()" in python
    assert 'Sys.info()[["nodename"]]' in r
    assert "ANCHOR_EXECUTION_HOST=" in python and "ANCHOR_EXECUTION_HOST=" in r
    assert "subprocess" not in python and "system(" not in r
    with pytest.raises(NotebookRuntimeError):
        runtime_probe_code("remote-shell")
