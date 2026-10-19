"""Dedicated, same-host Jupyter service entrypoint and read-only launch planning.

This module installs no accounts, tasks, packages, proxies, or certificates. A
portable installer must provision a dedicated non-administrator Windows account,
a private service directory, and a password using ``jupyter server password``.
The service directory MUST be outside the notebook tree. Notebook root_dir is a
navigation boundary, NOT an OS sandbox or a multi-tenant security boundary.

Run the entrypoint with the selected environment's Python in isolated mode:
``python -I notebook_service.py --settings <private-service-settings.json>``.
The settings document contains ``runtime`` (notebook_runtime's public contract)
and ``service`` (local deployment options). No password or token is accepted in
arguments or environment variables. Password hashes are read only into memory.

Configuration references (verified 2026-09-08):
https://jupyter-server.readthedocs.io/en/latest/other/full-config.html
https://jupyter-client.readthedocs.io/en/stable/provisioning.html
https://github.com/jupyter/jupyter_client/blob/main/jupyter_client/kernelspec.py
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
import ctypes
from ctypes import wintypes
import ipaddress
import json
import os
from pathlib import Path
import re
import stat
import sys
from typing import Callable, Mapping
from urllib.parse import urlsplit


class NotebookServiceError(ValueError):
    """A safe, actionable startup error; never includes provider credentials."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def _fail(code: str, message: str):
    raise NotebookServiceError(code, message)


def _local_path(value: object, *, directory: bool, label: str) -> Path:
    if not isinstance(value, str) or not value or any(c in value for c in "\x00\r\n"):
        _fail("invalid_path", f"{label} must be an explicit local absolute path.")
    path = Path(value)
    if not path.is_absolute() or value.startswith(("\\\\", "//")):
        _fail("invalid_path", f"{label} must be an explicit local absolute path.")
    if os.name == "nt":
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.GetDriveTypeW.argtypes = [wintypes.LPCWSTR]
        kernel.GetDriveTypeW.restype = wintypes.UINT
        if kernel.GetDriveTypeW(path.anchor) != 3:  # DRIVE_FIXED, never a mapped network drive.
            _fail("local_disk_required", f"{label} must be on a local fixed disk.")
    # Reject junction/reparse traversal before resolving away the evidence.
    for component in (path, *path.parents):
        try:
            attrs = component.lstat()
        except OSError:
            _fail("missing_path", f"{label} must already exist.")
        if stat.S_ISLNK(attrs.st_mode) or getattr(attrs, "st_file_attributes", 0) & 0x400:
            _fail("reparse_path", f"{label} must not traverse a symlink or reparse point.")
    correct_type = path.is_dir() if directory else path.is_file()
    if not correct_type:
        _fail("invalid_path", f"{label} has the wrong filesystem type.")
    if not directory and path.stat().st_nlink != 1:
        _fail("linked_file", f"{label} must not have additional hard links.")
    return path.resolve(strict=True)


def _inside(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False


def _winapi():
    if os.name != "nt":
        _fail("unsupported_platform", "This service adapter currently requires Windows.")
    advapi = ctypes.WinDLL("advapi32", use_last_error=True)
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    advapi.ConvertSidToStringSidW.argtypes = [ctypes.c_void_p, ctypes.POINTER(wintypes.LPWSTR)]
    advapi.ConvertSidToStringSidW.restype = wintypes.BOOL
    kernel.LocalFree.argtypes = [ctypes.c_void_p]
    kernel.LocalFree.restype = ctypes.c_void_p
    return advapi, kernel


def _sid_text(sid, advapi, kernel) -> str:
    rendered = wintypes.LPWSTR()
    if not sid or not advapi.ConvertSidToStringSidW(sid, ctypes.byref(rendered)):
        _fail("security_probe_failed", "Could not verify a Windows security identity.")
    try:
        return rendered.value
    finally:
        kernel.LocalFree(ctypes.cast(rendered, ctypes.c_void_p))


def current_windows_account() -> dict[str, object]:
    """Read the process token, including filtered-admin membership; no subprocess."""
    advapi, kernel = _winapi()
    kernel.GetCurrentProcess.restype = wintypes.HANDLE
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    advapi.OpenProcessToken.argtypes = [wintypes.HANDLE, wintypes.DWORD, ctypes.POINTER(wintypes.HANDLE)]
    advapi.OpenProcessToken.restype = wintypes.BOOL
    advapi.GetTokenInformation.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p,
                                          wintypes.DWORD, ctypes.POINTER(wintypes.DWORD)]
    advapi.GetTokenInformation.restype = wintypes.BOOL
    token = wintypes.HANDLE()
    if not advapi.OpenProcessToken(kernel.GetCurrentProcess(), 0x0008, ctypes.byref(token)):
        _fail("security_probe_failed", "Could not inspect the notebook service account.")
    try:
        def token_info(kind):
            size = wintypes.DWORD()
            advapi.GetTokenInformation(token, kind, None, 0, ctypes.byref(size))
            if not size.value:
                _fail("security_probe_failed", "Could not inspect the notebook service token.")
            data = ctypes.create_string_buffer(size.value)
            if not advapi.GetTokenInformation(token, kind, data, size, ctypes.byref(size)):
                _fail("security_probe_failed", "Could not inspect the notebook service token.")
            return data

        user_data = token_info(1)  # TokenUser begins with SID_AND_ATTRIBUTES.
        user_sid = _sid_text(ctypes.c_void_p.from_buffer(user_data).value, advapi, kernel)
        elevation = wintypes.DWORD.from_buffer(token_info(18)).value  # TokenElevationType
        # TokenGroups includes deny-only administrator membership in filtered tokens.
        class SidAndAttributes(ctypes.Structure):
            _fields_ = [("Sid", ctypes.c_void_p), ("Attributes", wintypes.DWORD)]

        class GroupsHeader(ctypes.Structure):
            _fields_ = [("GroupCount", wintypes.DWORD), ("Groups", SidAndAttributes * 1)]

        groups = token_info(2)
        count = wintypes.DWORD.from_buffer(groups).value
        offset = GroupsHeader.Groups.offset
        admin = elevation in (2, 3)
        for index in range(count):
            entry = SidAndAttributes.from_buffer(groups, offset + index * ctypes.sizeof(SidAndAttributes))
            if _sid_text(entry.Sid, advapi, kernel) == "S-1-5-32-544":
                admin = True
        secur32 = ctypes.WinDLL("secur32", use_last_error=True)
        secur32.GetUserNameExW.argtypes = [ctypes.c_int, wintypes.LPWSTR, ctypes.POINTER(wintypes.ULONG)]
        secur32.GetUserNameExW.restype = wintypes.BOOL
        size = wintypes.ULONG(512)
        name = ctypes.create_unicode_buffer(size.value)
        if not secur32.GetUserNameExW(2, name, ctypes.byref(size)):
            _fail("security_probe_failed", "Could not resolve the notebook service account name.")
        return {"account": name.value, "sid": user_sid, "is_admin": admin, "platform": "nt"}
    finally:
        kernel.CloseHandle(token)


def verify_private_path(path: Path, account: Mapping[str, object]) -> None:
    """Require owner + DACL access limited to service user, SYSTEM, administrators.

    Does not repair permissions, follow links, or accept a NULL DACL. Unrecognized
    access-allow ACE types fail closed. Provisioning is an explicit installer step.
    """
    advapi, kernel = _winapi()
    advapi.GetNamedSecurityInfoW.argtypes = [wintypes.LPWSTR, ctypes.c_int, wintypes.DWORD,
        ctypes.POINTER(ctypes.c_void_p), ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p),
        ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p)]
    advapi.GetNamedSecurityInfoW.restype = wintypes.DWORD
    advapi.GetAclInformation.argtypes = [ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.c_int]
    advapi.GetAclInformation.restype = wintypes.BOOL
    advapi.GetAce.argtypes = [ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(ctypes.c_void_p)]
    advapi.GetAce.restype = wintypes.BOOL
    owner, dacl, descriptor = ctypes.c_void_p(), ctypes.c_void_p(), ctypes.c_void_p()
    result = advapi.GetNamedSecurityInfoW(str(path), 1, 0x1 | 0x4, ctypes.byref(owner), None,
                                         ctypes.byref(dacl), None, ctypes.byref(descriptor))
    if result:
        _fail("private_directory_required", "Could not verify private notebook service permissions.")
    try:
        sid = str(account["sid"])
        if not dacl or _sid_text(owner, advapi, kernel) not in {sid, "S-1-5-18", "S-1-5-32-544"}:
            _fail("private_directory_required", "Notebook service state must have a private owner and DACL.")

        class AclSizeInformation(ctypes.Structure):
            _fields_ = [("AceCount", wintypes.DWORD), ("AclBytesInUse", wintypes.DWORD),
                        ("AclBytesFree", wintypes.DWORD)]

        info = AclSizeInformation()
        if not advapi.GetAclInformation(dacl, ctypes.byref(info), ctypes.sizeof(info), 2):
            _fail("private_directory_required", "Could not inspect notebook service access rules.")
        service_access = False
        allowed = {sid, "S-1-5-18", "S-1-5-32-544"}
        for index in range(info.AceCount):
            ace = ctypes.c_void_p()
            if not advapi.GetAce(dacl, index, ctypes.byref(ace)):
                _fail("private_directory_required", "Could not inspect notebook service access rules.")
            ace_type = ctypes.c_ubyte.from_address(ace.value).value
            ace_flags = ctypes.c_ubyte.from_address(ace.value + 1).value
            if ace_type == 1:  # ACCESS_DENIED_ACE cannot grant access.
                continue
            if ace_type != 0:  # Avoid guessing object/callback ACE semantics.
                _fail("private_directory_required", "Notebook service state has an unsupported access rule.")
            principal = _sid_text(ace.value + 8, advapi, kernel)
            if principal not in allowed:
                _fail("private_directory_required", "Notebook service state grants access to another account or group.")
            if principal == sid and not (ace_flags & 0x08):  # Not inherit-only.
                service_access = True
        if not service_access:
            _fail("private_directory_required", "The dedicated account needs explicit access to service state.")
    finally:
        kernel.LocalFree(descriptor)


def _runtime_validator(config):
    # Lazy import keeps the isolated script entrypoint independent of cwd.
    module_dir = str(Path(__file__).resolve().parent)
    if module_dir not in sys.path:
        sys.path.insert(0, module_dir)
    from notebook_runtime import validate_config
    return validate_config(config)


def build_launch_plan(runtime_config: Mapping[str, object], service: Mapping[str, object], *,
                      account_probe: Callable = current_windows_account,
                      private_path_check: Callable = verify_private_path,
                      runtime_validator: Callable = _runtime_validator,
                      environ: Mapping[str, str] | None = None) -> dict[str, object]:
    """Read-only validation/plan API. Injection seams never run in the CLI path."""
    allowed = {"runtime_dir", "password_file", "service_account", "dedicated_account_confirmed",
               "port", "listen_host", "runtime_paths", "r_library_dirs"}
    if not isinstance(service, Mapping) or set(service) - allowed:
        _fail("invalid_service_options", "Unknown notebook service option.")
    runtime = runtime_validator(runtime_config)
    if runtime.get("enabled") is not True:
        _fail("runtime_disabled", "Enable and configure the notebook runtime before starting its service.")
    if service.get("dedicated_account_confirmed") is not True:
        _fail("dedicated_account_required", "Confirm a dedicated non-administrator notebook account first.")
    expected = service.get("service_account")
    if not isinstance(expected, str) or not expected.strip() or "\\" not in expected:
        _fail("dedicated_account_required", "Specify the dedicated account as COMPUTER\\account or DOMAIN\\account.")
    account = dict(account_probe())
    if account.get("platform") != "nt" or not account.get("sid"):
        _fail("security_probe_failed", "A verified Windows service-account token is required.")
    if account["sid"] in {"S-1-5-18", "S-1-5-19", "S-1-5-20"}:
        _fail("dedicated_account_required", "Built-in shared Windows service identities are not dedicated notebook accounts.")
    if account.get("is_admin") is not False:
        _fail("administrator_account_forbidden", "Jupyter must run under a dedicated non-administrator account.")
    if str(account.get("account", "")).casefold() != expected.casefold():
        _fail("wrong_service_account", "The current account is not the configured notebook service account.")
    base = _local_path(service.get("runtime_dir"), directory=True, label="Service runtime directory")
    root = _local_path(runtime["root_dir"], directory=True, label="Notebook root")
    if _inside(base, root) or _inside(root, base):
        _fail("runtime_tree_overlap", "Notebook files and private service state must be separate trees.")
    password_file = _local_path(service.get("password_file"), directory=False, label="Jupyter password file")
    if not _inside(password_file, base):
        _fail("password_file_location", "The Jupyter password file must be inside private service state.")
    private_path_check(base, account)
    private_path_check(password_file, account)
    read_password_hash(password_file)
    host = service.get("listen_host", "127.0.0.1")
    try:
        if not ipaddress.ip_address(host).is_loopback:
            raise ValueError()
    except (ValueError, TypeError):
        _fail("loopback_required", "The notebook service must listen on a literal loopback address.")
    port = service.get("port", 8890)
    if isinstance(port, bool) or not isinstance(port, int) or not 1024 <= port <= 65535:
        _fail("invalid_port", "Choose a fixed notebook service port from 1024 through 65535.")
    specs = runtime.get("local_kernel_specs", {})
    if not isinstance(specs, Mapping) or not specs or set(specs) - {"python3", "ir"}:
        _fail("local_kernels_required", "Only explicitly configured local python3 and ir kernels are supported.")
    directories = {name: str(base / name) for name in
        ("config", "data", "runtime", "profile", "temp", "ipython", "lab-settings", "lab-workspaces", "r-libraries")}
    kernels = {}
    for name, argv in specs.items():
        kernels[name] = {"argv": list(argv), "display_name": "Python 3" if name == "python3" else "R",
                         "language": "python" if name == "python3" else "R",
                         "metadata": {"kernel_provisioner": {"provisioner_name": "local-provisioner", "config": {}}},
                         "env": {}}
    paths = []
    for key in ("runtime_paths", "r_library_dirs"):
        entries = service.get(key, [])
        if not isinstance(entries, list) or any(not isinstance(item, str) for item in entries):
            _fail("invalid_runtime_paths", "Runtime and R library paths must be explicit lists of local directories.")
        validated = [str(_local_path(item, directory=True, label=key)) for item in entries]
        if key == "runtime_paths":
            paths = validated
        else:
            r_libraries = validated or [directories["r-libraries"]]
    plan = {"schema_version": 1, "execution_host": runtime["execution_host"], "runtime": runtime,
            "service": dict(service), "account": account, "runtime_dir": str(base),
            "password_file": str(password_file), "listen_host": str(host), "port": port,
            "directories": directories, "kernels": kernels, "runtime_paths": paths,
            "r_library_dirs": r_libraries,
            "warnings": ["Trusted single-user workspace; root_dir is not an OS sandbox.",
                         "HTTPS proxy, startup task, account provisioning and live kernel host proof are separate deployment gates."]}
    plan["environment"] = build_environment(plan, os.environ if environ is None else environ)
    return plan


def build_environment(plan: Mapping[str, object], inherited: Mapping[str, str]) -> dict[str, str]:
    """Allowlist OS necessities, never copy inherited PATH, AI or Jupyter settings."""
    source = {key.upper(): value for key, value in inherited.items()}
    env = {key: source[key] for key in ("SYSTEMROOT", "WINDIR", "COMSPEC", "PATHEXT") if key in source}
    dirs = plan["directories"]
    paths = [str(Path(spec["argv"][0]).parent) for spec in plan["kernels"].values()]
    paths.extend(plan["runtime_paths"])
    system_root = source.get("SYSTEMROOT", source.get("WINDIR"))
    if system_root:
        env.setdefault("SYSTEMROOT", system_root)
        env.setdefault("WINDIR", system_root)
        paths.extend((str(Path(system_root) / "System32"), system_root))
    env.setdefault("PATHEXT", ".COM;.EXE;.BAT;.CMD")
    env.update({"PATH": os.pathsep.join(dict.fromkeys(paths)), "USERPROFILE": dirs["profile"],
                "HOME": dirs["profile"], "APPDATA": str(Path(dirs["profile"]) / "AppData" / "Roaming"),
                "LOCALAPPDATA": str(Path(dirs["profile"]) / "AppData" / "Local"),
                "TEMP": dirs["temp"], "TMP": dirs["temp"], "JUPYTER_CONFIG_DIR": dirs["config"],
                "JUPYTER_DATA_DIR": dirs["data"], "JUPYTER_RUNTIME_DIR": dirs["runtime"],
                "IPYTHONDIR": dirs["ipython"], "PYTHONNOUSERSITE": "1", "PYTHONUTF8": "1",
                "JUPYTERLAB_SETTINGS_DIR": dirs["lab-settings"], "JUPYTERLAB_WORKSPACES_DIR": dirs["lab-workspaces"],
                "R_LIBS_USER": os.pathsep.join(plan["r_library_dirs"])})
    empty = str(Path(dirs["config"]) / "empty-r-startup")
    env.update({key: empty for key in ("R_ENVIRON", "R_ENVIRON_USER", "R_PROFILE", "R_PROFILE_USER")})
    return env


def validate_process_environment(environment: Mapping[str, str]) -> None:
    """Reject an incomplete Windows process floor before changing this process."""
    required = ("SYSTEMROOT", "WINDIR", "PATHEXT", "PATH", "TEMP", "TMP")
    if (not isinstance(environment, Mapping) or any(
            not isinstance(environment.get(key), str) or not environment[key].strip()
            or "\x00" in environment[key] for key in required)):
        _fail("windows_environment_incomplete", "The isolated Windows runtime is missing required OS paths; check notebook service setup.")


def read_password_hash(path: Path) -> str:
    """Accept Jupyter's password JSON only, never execute an external config file."""
    try:
        if path.stat().st_size > 65536:
            raise ValueError()
        config = json.loads(path.read_text(encoding="utf-8"))
        values = [config.get(section, {}).get("hashed_password")
                  for section in ("IdentityProvider", "PasswordIdentityProvider")]
        hashes = [item for item in values if item is not None]
        if not hashes or any(item != hashes[0] for item in hashes):
            raise ValueError()
        value = hashes[0]
        if not isinstance(value, str) or len(value) > 4096 or any(c in value for c in "\r\n\x00"):
            raise ValueError()
        # Jupyter passwd() uses argon2; reject plaintext and obsolete weak hashes.
        if not re.fullmatch(r"argon2:\$argon2(?:id|i)\$v=\d+\$m=\d+,t=\d+,p=\d+\$[A-Za-z0-9+/=]+\$[A-Za-z0-9+/=]+", value):
            raise ValueError()
        return value
    except (OSError, ValueError, TypeError, AttributeError):
        _fail("password_setup_required", "Run Jupyter's own password setup into the private password JSON file first.")


def _write_managed(path: Path, content: str, account: Mapping[str, object], private_path_check: Callable):
    """Create once, or accept identical managed content. Never overwrite unknown files."""
    if path.exists():
        _local_path(str(path), directory=False, label="Managed service file")
        private_path_check(path, account)
        if path.read_text(encoding="utf-8") != content:
            _fail("managed_file_conflict", "A managed notebook service file differs; explicit migration is required.")
        return
    with path.open("x", encoding="utf-8", newline="\n") as handle:
        handle.write(content)
        handle.flush()
        os.fsync(handle.fileno())
    private_path_check(path, account)


def _ensure_managed_dir(path: Path, base: Path, account: Mapping[str, object], private_path_check: Callable):
    """Check each existing component before creating a child beneath it."""
    if not _inside(path, base) or ".." in path.relative_to(base).parts:
        _fail("invalid_managed_path", "Managed notebook state escaped its private directory.")
    current = base
    for component in path.relative_to(base).parts:
        current = current / component
        if not current.exists():
            current.mkdir(mode=0o700)
        _local_path(str(current), directory=True, label="Managed service directory")
        private_path_check(current, account)


def prepare_runtime(plan: Mapping[str, object], *, private_path_check: Callable = verify_private_path) -> None:
    """Write isolated folders and exact local specs; does not launch or execute code."""
    account = plan["account"]
    base = _local_path(plan["runtime_dir"], directory=True, label="Service runtime directory")
    private_path_check(base, account)
    for name in (*plan["directories"].values(), plan["environment"]["APPDATA"], plan["environment"]["LOCALAPPDATA"]):
        path = Path(name)
        _ensure_managed_dir(path, base, account, private_path_check)
    _write_managed(Path(plan["directories"]["config"]) / "empty-r-startup", "", account, private_path_check)
    for name, spec in plan["kernels"].items():
        directory = Path(plan["directories"]["data"]) / "kernels" / name
        _ensure_managed_dir(directory, base, account, private_path_check)
        _write_managed(directory / "kernel.json", json.dumps(spec, ensure_ascii=False, indent=2) + "\n",
                       account, private_path_check)
    marker = {"schema_version": 1, "execution_host": plan["execution_host"],
              "account_sid": account["sid"], "purpose": "anchor-notebook-service"}
    _write_managed(base / "anchor-notebook-service.json", json.dumps(marker, sort_keys=True) + "\n",
                   account, private_path_check)


@contextmanager
def runtime_lease(plan: Mapping[str, object]):
    """Exclusive owned-runtime lock. Never adopt, signal, or kill a foreign process."""
    if os.name != "nt":
        _fail("unsupported_platform", "The service lock currently requires Windows.")
    import msvcrt
    path = Path(plan["runtime_dir"]) / ".service.lock"
    if path.exists():
        _local_path(str(path), directory=False, label="Service lock")
        verify_private_path(path, plan["account"])
    with path.open("a+b") as handle:
        verify_private_path(path, plan["account"])
        handle.seek(0)
        if not handle.read(1):
            handle.write(b"0")
            handle.flush()
        handle.seek(0)
        try:
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError:
            _fail("service_already_running", "This notebook service runtime is already owned by another process.")
        try:
            yield
        finally:
            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)


def jupyter_config(plan: Mapping[str, object], password_hash: str) -> dict[str, object]:
    """In-memory Jupyter Server 2.x config. Never serialize or log this dictionary."""
    origin = urlsplit(plan["runtime"]["public_base_url"])
    dirs = plan["directories"]
    return {"ServerApp": {"ip": plan["listen_host"], "port": plan["port"], "port_retries": 0,
        "root_dir": plan["runtime"]["root_dir"], "base_url": origin.path or "/", "default_url": "/lab",
        "open_browser": False, "allow_root": False, "allow_remote_access": False,
        "local_hostnames": ["localhost", origin.hostname], "allow_origin": "", "allow_origin_pat": "",
        "disable_check_xsrf": False, "allow_unauthenticated_access": False,
        "trust_xheaders": False, "terminals_enabled": False, "allow_external_kernels": False,
        "shutdown_no_activity_timeout": 0, "cookie_secret_file": str(Path(dirs["runtime"]) / "cookie_secret"),
        "jpserver_extensions": {"jupyterlab": True}, "reraise_server_extension_failures": True},
        "IdentityProvider": {"token": "", "cookie_options": {"secure": origin.scheme == "https", "httponly": True, "samesite": "Lax"}},
        "PasswordIdentityProvider": {"hashed_password": password_hash, "password_required": True, "allow_password_change": False},
        "KernelSpecManager": {"allowed_kernelspecs": set(plan["kernels"]), "ensure_native_kernel": False},
        "GatewayClient": {"url": "", "ws_url": ""},
        "KernelProvisionerFactory": {"default_provisioner_name": "local-provisioner"},
        "SessionManager": {"database_filepath": str(Path(dirs["runtime"]) / "sessions.sqlite")}}


def run_jupyter(plan: Mapping[str, object], password_hash: str) -> None:
    """Foreground process; imports Jupyter only after stripping inherited settings."""
    validate_process_environment(plan["environment"])
    os.environ.clear()
    os.environ.update(plan["environment"])
    try:
        from jupyter_server.serverapp import ServerApp
        from jupyter_server.auth.identity import PasswordIdentityProvider
        from jupyter_server.services.kernels.kernelmanager import AsyncMappingKernelManager
        from jupyter_client.kernelspec import KernelSpecManager, NoSuchKernel
        from traitlets.config import Config
    except ImportError:
        _fail("dependencies_missing", "Install JupyterLab, Jupyter Server, and ipykernel in the selected service environment.")

    class LocalKernelSpecManager(KernelSpecManager):
        def __init__(self, **kwargs):
            kwargs["kernel_dirs"] = [str(Path(plan["directories"]["data"]) / "kernels")]
            kwargs["allowed_kernelspecs"] = set(plan["kernels"])
            kwargs["ensure_native_kernel"] = False
            super().__init__(**kwargs)

        def get_kernel_spec(self, kernel_name):
            if kernel_name not in plan["kernels"]:
                raise NoSuchKernel(kernel_name)
            spec = super().get_kernel_spec(kernel_name)
            approved = plan["kernels"][kernel_name]
            if (spec.argv != approved["argv"] or spec.env != approved["env"]
                    or spec.metadata != approved["metadata"]):
                raise NoSuchKernel(kernel_name)
            return spec

    class IsolatedServerApp(ServerApp):
        @property
        def config_file_paths(self):
            return [plan["directories"]["config"]]

        def load_config_file(self, *args, **kwargs):
            # Only the explicit in-memory configuration is authoritative.
            return None

    config = Config(jupyter_config(plan, password_hash))
    config.ServerApp.identity_provider_class = PasswordIdentityProvider
    config.ServerApp.kernel_spec_manager_class = LocalKernelSpecManager
    config.ServerApp.kernel_manager_class = AsyncMappingKernelManager
    # These are traits but not configurable traits in Jupyter Server 2.x.
    # Explicit constructor values also avoid cached defaults from prior imports.
    app = IsolatedServerApp(config=config, runtime_dir=plan["directories"]["runtime"],
                            config_dir=plan["directories"]["config"], data_dir=plan["directories"]["data"])
    app.initialize(argv=[], find_extensions=False)
    if (app.gateway_config.gateway_enabled or app.identity_provider.token
            or not app.identity_provider.hashed_password
            or type(app.identity_provider) is not PasswordIdentityProvider
            or type(app.kernel_manager) is not AsyncMappingKernelManager
            or type(app.kernel_spec_manager) is not LocalKernelSpecManager
            or app.ip != plan["listen_host"] or app.port != plan["port"]
            or app.allow_remote_access or app.allow_external_kernels
            or app.disable_check_xsrf or app.allow_unauthenticated_access or app.trust_xheaders
            or any(Path(getattr(app, name + "_dir")) != Path(plan["directories"][name])
                   for name in ("runtime", "config", "data"))):
        _fail("jupyter_security_contract", "Jupyter did not honor the required local-kernel/password configuration.")
    app.start()


def serve(runtime_config: Mapping[str, object], service_options: Mapping[str, object]) -> None:
    """Validate again under the actual service account, acquire ownership, then run."""
    plan = build_launch_plan(runtime_config, service_options)
    with runtime_lease(plan):
        prepare_runtime(plan)
        password_file = _local_path(plan["password_file"], directory=False, label="Jupyter password file")
        verify_private_path(password_file, plan["account"])
        password_hash = read_password_hash(password_file)
        run_jupyter(plan, password_hash)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Dedicated same-host Anchor notebook service (no installation).")
    parser.add_argument("--settings", required=True, help="Private JSON containing runtime and service configuration")
    args = parser.parse_args(argv)
    try:
        if not sys.flags.isolated:
            _fail("isolated_python_required", "Start the notebook service with Python -I.")
        settings_path = _local_path(args.settings, directory=False, label="Service settings")
        account = current_windows_account()
        verify_private_path(settings_path, account)
        if settings_path.stat().st_size > 1024 * 1024:
            _fail("invalid_service_settings", "Service settings exceed the supported size.")
        document = json.loads(settings_path.read_text(encoding="utf-8"))
        if not isinstance(document, dict) or set(document) != {"runtime", "service"}:
            _fail("invalid_service_settings", "Service settings require exactly runtime and service objects.")
        serve(document["runtime"], document["service"])
        return 0
    except NotebookServiceError as exc:
        print(f"Notebook service unavailable [{exc.code}]: {exc}", file=sys.stderr)
        return 2
    except (OSError, ValueError, TypeError):
        print("Notebook service unavailable: invalid or unreadable local configuration.", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
