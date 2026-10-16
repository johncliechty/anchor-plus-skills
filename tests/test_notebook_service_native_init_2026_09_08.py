"""Installed-library canary, not a service-account or filesystem-security proof.

The synthetic account and no-op private-path verifier are deliberate: native
Jupyter initialization is the subject of this test. No Jupyter listener, event-loop
service, kernel, account setup, or real password is permitted. All runtime
files belong to pytest's temporary directory.
"""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
import socket
import subprocess
import sys

import pytest

import notebook_service as service


pytestmark = pytest.mark.skipif(
    os.name != "nt", reason="The notebook host service is Windows-only."
)

# A deliberately synthetic, non-secret Argon2-shaped value. This test does not
# authenticate a browser or create a password for any real account.
HASH = (
    "argon2:$argon2id$v=19$m=10240,t=10,p=8"
    "$c3ludGhldGljc2FsdA$c3ludGhldGljaGFzaA"
)


def _synthetic_plan(tmp_path: Path, original_environment: dict[str, str]) -> dict:
    workspace = tmp_path / "notebooks"
    private = tmp_path / "private-service-state"
    workspace.mkdir()
    private.mkdir()
    directories = {
        name: str(private / name)
        for name in (
            "config",
            "data",
            "runtime",
            "profile",
            "temp",
            "ipython",
            "lab-settings",
            "lab-workspaces",
            "r-libraries",
        )
    }
    plan = {
        "execution_host": socket.gethostname(),
        "runtime_dir": str(private),
        "account": {
            "platform": "nt",
            "sid": "S-1-5-21-100-100-100-1010",
            "account": "SYNTHETIC\\NotebookRunner",
            "is_admin": False,
        },
        "directories": directories,
        "runtime": {
            "root_dir": str(workspace),
            "public_base_url": "https://notebooks.example.test/",
            "execution_host": socket.gethostname(),
        },
        "listen_host": "127.0.0.1",
        "port": 8891,
        "kernels": {
            "python3": {
                "argv": [
                    sys.executable,
                    "-m",
                    "ipykernel_launcher",
                    "-f",
                    "{connection_file}",
                ],
                "display_name": "Python 3",
                "language": "python",
                "metadata": {
                    "kernel_provisioner": {
                        "provisioner_name": "local-provisioner", "config": {}
                    }
                },
                "env": {},
            }
        },
        "runtime_paths": [],
        "r_library_dirs": [directories["r-libraries"]],
    }
    plan["environment"] = service.build_environment(plan, original_environment)
    return plan


@pytest.fixture
def native_initialized_server(tmp_path, monkeypatch):
    """Initialize the real libraries while forbidding all launch operations."""
    serverapp = pytest.importorskip("jupyter_server.serverapp")
    pytest.importorskip("jupyterlab")
    gateway = pytest.importorskip("jupyter_server.gateway.gateway_client")
    provisioning = pytest.importorskip("jupyter_client.provisioning.factory")
    tornado_ioloop = pytest.importorskip("tornado.ioloop")
    jupyter_sysinfo = pytest.importorskip("jupyter_server._sysinfo")

    original_environment_object = os.environ
    original_loop_policy = asyncio.get_event_loop_policy()
    owned_loop = None
    owned_ioloop = None
    incoming = dict(original_environment_object)
    # These are synthetic pollution probes, not credentials. They must not
    # survive the service's replacement environment.
    probes = {
        "OPENAI_API_KEY": "synthetic-must-be-removed",
        "XAI_API_KEY": "synthetic-must-be-removed",
        "JUPYTER_GATEWAY_URL": "https://untrusted.invalid/",
        "JUPYTER_CONFIG_PATH": str(tmp_path / "untrusted-config"),
    }
    incoming.update(probes)
    plan = _synthetic_plan(tmp_path, incoming)
    initialized = []
    started = []
    forbidden_calls = []
    original_initialize = serverapp.ServerApp.initialize

    def reject_launch(*_args, **_kwargs):
        forbidden_calls.append(True)
        raise AssertionError("Native-init canary attempted a bind or child process")

    def initialize_without_http_server(app, *args, **kwargs):
        assert kwargs.get("argv") == []
        assert kwargs.get("find_extensions") is False
        # This is an actual Jupyter initialize call, not a mocked initializer.
        # The installed ServerApp API exposes this explicit no-listener seam.
        kwargs["new_httpserver"] = False
        result = original_initialize(app, *args, **kwargs)
        initialized.append(app)
        return result

    def capture_start(app, *_args, **_kwargs):
        # The production security checks must finish and reach start, but the
        # original start method (and therefore its run loop) is never called.
        started.append(app)

    try:
        with monkeypatch.context() as patch:
            # os is a shared module. Replacing only its environ object keeps
            # clear/update inside run_jupyter away from the real process
            # environment, and monkeypatch restores the exact object finally.
            patch.setattr(service.os, "environ", dict(incoming))
            patch.setattr(subprocess, "Popen", reject_launch)
            # Installed-package Git/version diagnostics are not the subject
            # of this canary. Stub only that diagnostic; no child process is
            # permitted for it or for any part of Jupyter initialization.
            patch.setattr(
                jupyter_sysinfo,
                "pkg_commit_hash",
                lambda *_args, **_kwargs: ("synthetic-canary", "not-a-live-commit"),
            )
            # Windows' selector loop creates an internal socketpair, briefly
            # using a loopback bind. Fully construct our owned loop before
            # forbidding binds; no Jupyter initialization has occurred yet.
            # A separate policy preserves the previous policy's loop state.
            owned_policy = asyncio.WindowsSelectorEventLoopPolicy()
            asyncio.set_event_loop_policy(owned_policy)
            owned_loop = owned_policy.new_event_loop()
            owned_policy.set_event_loop(owned_loop)
            owned_ioloop = tornado_ioloop.IOLoop.current()
            assert owned_ioloop.asyncio_loop is owned_loop
            patch.setattr(socket.socket, "bind", reject_launch)
            patch.setattr(serverapp.ServerApp, "initialize", initialize_without_http_server)
            patch.setattr(serverapp.ServerApp, "start", capture_start)
            # The real Jupyter factories are singletons. Do not inherit an
            # earlier test's configuration or leave ours behind for later tests.
            patch.setattr(gateway.GatewayClient, "_instance", None)
            patch.setattr(provisioning.KernelProvisionerFactory, "_instance", None)

            service.prepare_runtime(plan, private_path_check=lambda *_: None)
            service.run_jupyter(plan, HASH)

            assert len(initialized) == 1
            assert started == initialized
            assert not forbidden_calls
            assert all(name not in service.os.environ for name in probes)
            assert service.os.environ == plan["environment"]
            assert getattr(initialized[0], "http_server", None) is None
            assert initialized[0].io_loop is owned_ioloop
            for directory_name in ("runtime", "config", "data"):
                assert Path(getattr(initialized[0], directory_name + "_dir")) == Path(
                    plan["directories"][directory_name]
                )
            yield initialized[0], plan
            assert not forbidden_calls
    finally:
        try:
            if owned_ioloop is not None:
                # Tornado removes its loop mapping and closes the underlying
                # asyncio loop. Never close a loop belonging to another test.
                owned_ioloop.close(all_fds=True)
        finally:
            try:
                if owned_loop is not None and not owned_loop.is_closed():
                    owned_loop.close()
            finally:
                asyncio.set_event_loop_policy(original_loop_policy)
                assert os.environ is original_environment_object


def test_actual_jupyter_initialization_retains_local_authenticated_contract(
    native_initialized_server,
):
    app, plan = native_initialized_server
    identity = pytest.importorskip("jupyter_server.auth.identity")
    managers = pytest.importorskip("jupyter_server.services.kernels.kernelmanager")

    assert type(app.identity_provider) is identity.PasswordIdentityProvider
    assert app.identity_provider.hashed_password == HASH
    assert app.identity_provider.token == ""
    assert app.identity_provider.password_required is True
    assert app.identity_provider.allow_password_change is False
    assert type(app.kernel_manager) is managers.AsyncMappingKernelManager
    assert type(app.kernel_spec_manager).__name__ == "LocalKernelSpecManager"
    assert type(app.kernel_spec_manager).__module__ == service.__name__
    assert app.kernel_manager.list_kernel_ids() == []
    assert app.gateway_config.gateway_enabled is False
    assert app.gateway_config.url == ""
    assert app.gateway_config.ws_url == ""
    assert app.ip == plan["listen_host"]
    assert app.port == plan["port"]
    assert app.port_retries == 0
    assert app.root_dir == plan["runtime"]["root_dir"]
    assert app.allow_remote_access is False
    assert app.allow_external_kernels is False
    assert app.disable_check_xsrf is False
    assert app.allow_unauthenticated_access is False
    assert app.trust_xheaders is False
    assert app.open_browser is False
    assert {
        name for name, enabled in app.jpserver_extensions.items() if enabled
    } == {"jupyterlab"}


def test_actual_local_manager_rejects_unknown_and_drifted_specs_without_restart(
    native_initialized_server,
):
    app, plan = native_initialized_server
    kernelspec = pytest.importorskip("jupyter_client.kernelspec")
    manager = app.kernel_spec_manager
    approved = plan["kernels"]["python3"]
    kernel_file = Path(plan["directories"]["data"]) / "kernels" / "python3" / "kernel.json"
    original = kernel_file.read_bytes()

    def assert_known_spec():
        actual = manager.get_kernel_spec("python3")
        assert actual.argv == approved["argv"]
        assert actual.env == approved["env"]
        assert actual.metadata == approved["metadata"]

    assert set(manager.find_kernel_specs()) == {"python3"}
    assert_known_spec()
    with pytest.raises(kernelspec.NoSuchKernel):
        manager.get_kernel_spec("unregistered-local-kernel")

    # Repeated reads on the same manager must validate the actual owned file,
    # including after a successful first lookup. Restoration is exact bytes.
    for changed_field in ("argv", "env", "metadata"):
        changed = json.loads(original)
        if changed_field == "argv":
            changed["argv"] = [sys.executable, "-c", "raise AssertionError('unused')"]
        elif changed_field == "env":
            changed["env"] = {"UNAPPROVED_RUNTIME_SETTING": "synthetic"}
        else:
            changed["metadata"] = {
                "kernel_provisioner": {"provisioner_name": "unapproved-provisioner"}
            }
        try:
            kernel_file.write_text(json.dumps(changed), encoding="utf-8")
            with pytest.raises(kernelspec.NoSuchKernel):
                manager.get_kernel_spec("python3")
        finally:
            kernel_file.write_bytes(original)
        assert_known_spec()

    assert kernel_file.read_bytes() == original
    assert app.kernel_manager.list_kernel_ids() == []
