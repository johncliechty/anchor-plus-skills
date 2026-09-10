"""Portable, non-launching contract for a same-host Jupyter service.

Jupyter owns its login cookie and HTTPS/WSS origin.  These helpers neither proxy
authentication nor install, start, stop, adopt, or execute anything.  ``root_dir``
is a navigation boundary, NOT an operating-system sandbox: this is a trusted,
single-user workspace design, not a multi-tenant execution boundary.

Configuration belongs in the caller's private Anchor runtime-data directory,
never in distributable project artifacts.  This module deliberately performs no
configuration-file I/O.  A config declares local kernels; actual kernel-host
attestation additionally requires running the returned probe in Jupyter.  The
service owner must launch Jupyter with an isolated environment and without a
remote gateway/provisioner.  Inspecting an unrelated running service is not a
substitute for that setup.

Schema 1 fields: schema_version, enabled, public_base_url, root_dir,
execution_host, local_kernel_specs.  The optional allow_loopback_dev flag permits
HTTP only for a literal loopback address or localhost.  Kernel specs are argv
lists for python3 and/or ir, not arbitrary kernelspec dictionaries.  Missing R
does not prevent a Python-only configuration from being valid.
"""

from __future__ import annotations

import ipaddress
import re
import socket
from collections.abc import Mapping
from pathlib import Path, PurePosixPath, PureWindowsPath
from urllib.parse import quote, unquote, urlsplit, urlunsplit


SCHEMA_VERSION = 1
SECURITY_NOTICE = (
    "Jupyter requires its own login. The configured root is not an OS sandbox; "
    "use a trusted single-user workspace. Local-kernel configuration is not "
    "a substitute for a successful kernel execution-host probe."
)
_FIELDS = {
    "schema_version", "schema", "enabled", "public_base_url", "root_dir",
    "execution_host", "local_kernel_specs", "allow_loopback_dev",
}
_CONTROL = re.compile(r"[\x00-\x20\x7f]")
_PYTHON_EXECUTABLE = re.compile(r"python(?:w|\d+(?:\.\d+)*)?(?:\.exe)?", re.I)
_R_EXECUTABLE = re.compile(r"r(?:term)?(?:\.exe)?", re.I)
_WINDOWS_RESERVED = re.compile(r"(?:con|prn|aux|nul|com[1-9]|lpt[1-9])(?:\..*)?", re.I)


class NotebookRuntimeError(ValueError):
    """A safe-to-display error whose message never includes supplied secrets."""

    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(message)


def _fail(code: str, message: str) -> None:
    raise NotebookRuntimeError(code, message)


def _text(value: object, code: str, message: str) -> str:
    if not isinstance(value, str) or not value or value != value.strip():
        _fail(code, message)
    if any(ord(character) < 32 or ord(character) == 127 for character in value):
        _fail(code, message)
    return value


def _existing_local_path(value: object, *, directory: bool, code: str) -> Path:
    label = "directory" if directory else "executable file"
    path_text = _text(value, code, f"Configure an absolute existing local {label}.")
    # UNC and Windows device paths are not portable local-root declarations.
    if path_text.startswith(("\\\\", "//")):
        _fail(code, f"Configure an absolute existing local {label}, not a network path.")
    path = Path(path_text)
    if not path.is_absolute():
        _fail(code, f"Configure an absolute existing local {label}.")
    try:
        resolved = path.resolve(strict=True)
        exists = resolved.is_dir() if directory else resolved.is_file()
    except (OSError, RuntimeError, ValueError):
        _fail(code, f"The configured local {label} is unavailable.")
    if str(resolved).startswith(("\\\\", "//")) or not exists:
        _fail(code, f"The configured local {label} is unavailable.")
    return resolved


def _public_base_url(value: object, allow_loopback_dev: bool) -> str:
    raw = _text(value, "invalid_url", "Configure a token-free Jupyter base URL.")
    if _CONTROL.search(raw) or "\\" in raw or "?" in raw or "#" in raw:
        _fail("invalid_url", "Jupyter base URLs cannot contain credentials, queries, or fragments.")
    try:
        parsed = urlsplit(raw)
        hostname = parsed.hostname
        port = parsed.port
        if not hostname or parsed.username is not None or parsed.password is not None:
            raise ValueError("missing host or userinfo")
        if "%" in hostname:
            raise ValueError("encoded host or IPv6 scope")
        try:
            address = ipaddress.ip_address(hostname)
        except ValueError:
            address = None
            hostname = hostname.encode("idna").decode("ascii").lower().rstrip(".")
            if len(hostname) > 253 or any(
                not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", label)
                for label in hostname.split(".")
            ):
                raise ValueError("invalid hostname")
        loopback = hostname == "localhost" or (address is not None and address.is_loopback)
        if parsed.scheme != "https" and not (
            parsed.scheme == "http" and allow_loopback_dev and loopback
        ):
            _fail("https_required", "Jupyter requires HTTPS; HTTP is permitted only for explicit loopback development.")
        if address is not None:
            hostname = address.compressed
            if address.version == 6:
                hostname = f"[{hostname}]"
        netloc = hostname + (f":{port}" if port is not None else "")
        segments = parsed.path.split("/")
        if parsed.path and not parsed.path.startswith("/"):
            raise ValueError("invalid prefix")
        normalized = []
        for index, segment in enumerate(segments):
            if not segment:
                if index not in (0, len(segments) - 1):
                    raise ValueError("ambiguous path prefix")
                continue
            decoded = unquote(segment, errors="strict")
            if decoded in (".", "..") or any(c in decoded for c in ("/", "\\", "%", "?", "#")):
                raise ValueError("ambiguous encoded path")
            if _CONTROL.search(decoded):
                raise ValueError("control in path")
            normalized.append(quote(decoded, safe="-._~"))
        prefix = "/" + "/".join(normalized) if normalized else ""
        return urlunsplit((parsed.scheme, netloc, prefix, "", ""))
    except NotebookRuntimeError:
        raise
    except (ValueError, UnicodeError):
        _fail("invalid_url", "Configure an unambiguous, token-free Jupyter HTTPS base URL.")


def _kernel_argv(name: str, argv: object) -> list[str]:
    if not isinstance(argv, list) or not argv or any(not isinstance(arg, str) for arg in argv):
        _fail("invalid_kernel", "Local kernel specs must contain nonempty argv lists.")
    if any(any(ord(char) < 32 or ord(char) == 127 for char in arg) for arg in argv):
        _fail("invalid_kernel", "Local kernel arguments cannot contain control characters.")
    executable = _existing_local_path(argv[0], directory=False, code="invalid_kernel")
    arguments = argv[1:]
    # Require the direct, familiar local kernel entry points.  Merely accepting
    # an absolute ssh/docker/batch launcher would not establish local execution.
    if name == "python3":
        if not _PYTHON_EXECUTABLE.fullmatch(executable.name):
            _fail("invalid_kernel", "The Python kernel must use a direct local Python executable.")
        try:
            module_index = arguments.index("-m")
        except ValueError:
            _fail("invalid_kernel", "The Python kernel must directly launch ipykernel_launcher.")
        prefix = arguments[:module_index]
        if any(arg not in ("-Xfrozen_modules=off", "-Xfrozen_modules=on") for arg in prefix):
            _fail("invalid_kernel", "Unsupported Python kernel launcher options.")
        if arguments[module_index:] != ["-m", "ipykernel_launcher", "-f", "{connection_file}"]:
            _fail("invalid_kernel", "The Python kernel must directly launch ipykernel_launcher with its connection file.")
    else:
        if not _R_EXECUTABLE.fullmatch(executable.name):
            _fail("invalid_kernel", "The R kernel must use a direct local R executable.")
        if arguments not in (
            ["--slave", "-e", "IRkernel::main()", "--args", "{connection_file}"],
            ["--quiet", "--slave", "-e", "IRkernel::main()", "--args", "{connection_file}"],
        ):
            _fail("invalid_kernel", "The R kernel must directly launch IRkernel with its connection file.")
    return [str(executable), *arguments]


def validate_config(config: Mapping[str, object]) -> dict[str, object]:
    """Validate without changing config or launching anything; return safe fields.

    Unknown fields fail closed, including gateway, environment, provisioner, and
    token settings.  A schema alias is accepted for callers using ``schema: 1``;
    output always uses ``schema_version``.  Values are declarations of a managed
    local service, not evidence that an unrelated process follows them.
    """
    if not isinstance(config, Mapping):
        _fail("invalid_config", "Jupyter runtime configuration must be an object.")
    if any(not isinstance(key, str) for key in config) or set(config) - _FIELDS:
        _fail("unsupported_config", "Unsupported Jupyter settings; gateway, environment, provisioner, and token settings are not accepted.")
    schema = config.get("schema_version", config.get("schema"))
    if type(schema) is not int or schema != SCHEMA_VERSION:
        _fail("invalid_schema", "Jupyter runtime configuration requires schema version 1.")
    if "schema" in config and (type(config["schema"]) is not int or config["schema"] != schema):
        _fail("invalid_schema", "Jupyter runtime schema declarations must agree.")
    enabled = config.get("enabled")
    allow_loopback_dev = config.get("allow_loopback_dev", False)
    if type(enabled) is not bool or type(allow_loopback_dev) is not bool:
        _fail("invalid_config", "Jupyter enabled and loopback-development settings must be booleans.")
    public_url = _public_base_url(config.get("public_base_url"), allow_loopback_dev)
    root = _existing_local_path(config.get("root_dir"), directory=True, code="invalid_root")
    execution_host = _text(config.get("execution_host"), "invalid_host", "Configure the Anchor machine's execution hostname.")
    if execution_host.casefold().rstrip(".") != socket.gethostname().casefold().rstrip("."):
        _fail("host_mismatch", "The configured execution host is not this Anchor machine.")
    kernels = config.get("local_kernel_specs")
    if not isinstance(kernels, Mapping) or not kernels or set(kernels) - {"python3", "ir"}:
        _fail("invalid_kernel", "Configure direct local python3 and/or ir kernel argv lists.")
    normalized_kernels = {name: _kernel_argv(name, argv) for name, argv in kernels.items()}
    return {
        "schema_version": SCHEMA_VERSION,
        "enabled": enabled,
        "public_base_url": public_url,
        "root_dir": str(root),
        "execution_host": execution_host,
        "local_kernel_specs": normalized_kernels,
        "allow_loopback_dev": allow_loopback_dev,
    }


def _relative_notebook(value: object) -> tuple[str, ...]:
    relative = _text(value, "invalid_notebook_path", "Select a project-relative .ipynb notebook path.")
    windows_path = PureWindowsPath(relative)
    if windows_path.drive or windows_path.root or PurePosixPath(relative).is_absolute():
        _fail("invalid_notebook_path", "Notebook paths must be relative to the project.")
    parts = tuple(relative.replace("\\", "/").split("/"))
    if any(
        part in ("", ".", "..") or ":" in part or part.endswith((".", " "))
        or _WINDOWS_RESERVED.fullmatch(part)
        for part in parts
    ):
        _fail("invalid_notebook_path", "Notebook paths cannot contain traversal or ambiguous path segments.")
    if PurePosixPath(parts[-1]).suffix.lower() != ".ipynb":
        _fail("invalid_notebook_path", "The selected work product is not a Jupyter notebook.")
    return parts


def notebook_url(config: Mapping[str, object], project_root: str | Path, notebook_relative: str) -> str:
    """Build an authorized caller's token-free Jupyter /lab/tree navigation URL.

    Resolve both project and notebook paths before containment checks, including
    symlinks/junctions.  The caller still owns Anchor authorization and Jupyter
    owns its separate sign-in.  Filesystem changes after validation are not an
    OS sandbox guarantee and are outside this trusted-user helper's boundary.
    """
    validated = validate_config(config)
    if not validated["enabled"]:
        _fail("disabled", "Jupyter notebook execution is disabled.")
    root = Path(validated["root_dir"])
    project = _existing_local_path(str(project_root), directory=True, code="invalid_project")
    try:
        project.relative_to(root)
    except ValueError:
        _fail("project_outside_root", "The project is outside the configured Jupyter root.")
    parts = _relative_notebook(notebook_relative)
    try:
        notebook = project.joinpath(*parts).resolve(strict=True)
        notebook.relative_to(project)
        mapped = notebook.relative_to(root)
    except ValueError:
        _fail("notebook_outside_root", "The selected notebook resolves outside its authorized project.")
    except (OSError, RuntimeError):
        _fail("notebook_unavailable", "The selected notebook is unavailable.")
    if notebook.suffix.lower() != ".ipynb":
        _fail("invalid_notebook_path", "The selected path does not resolve to a Jupyter notebook.")
    try:
        available_file = notebook.is_file()
    except OSError:
        available_file = False
    if not available_file:
        _fail("notebook_unavailable", "The selected notebook is not an available file.")
    encoded_path = "/".join(quote(part, safe="-._~") for part in mapped.parts)
    return str(validated["public_base_url"]) + "/lab/tree/" + encoded_path


def runtime_probe_code(language: str) -> str:
    """Return minimal host evidence for a human to execute in a notebook cell."""
    if isinstance(language, str) and language.casefold() in ("python", "python3", "py"):
        return 'import socket\nprint("ANCHOR_EXECUTION_HOST=" + socket.gethostname())\n'
    if isinstance(language, str) and language.casefold() in ("r", "ir"):
        return 'cat("ANCHOR_EXECUTION_HOST=", unname(Sys.info()[["nodename"]]), "\\n", sep = "")\n'
    _fail("unsupported_language", "Execution-host probes support Python and R only.")


def runtime_status(config: Mapping[str, object] | None, *, include_paths: bool = False) -> dict[str, object]:
    """Produce a safe UI status; paths and the public origin are opt-in."""
    if config is None:
        return {
            "configured": False, "enabled": False, "status": "not_configured",
            "message": "A same-host Jupyter service has not been configured.",
            "security_notice": SECURITY_NOTICE,
        }
    try:
        validated = validate_config(config)
    except NotebookRuntimeError as error:
        return {
            "configured": False, "enabled": False, "status": "invalid",
            "error": error.code, "message": str(error), "security_notice": SECURITY_NOTICE,
        }
    result = {
        "configured": True,
        "enabled": validated["enabled"],
        "status": "ready" if validated["enabled"] else "disabled",
        "execution_host": validated["execution_host"],
        "kernels": sorted(validated["local_kernel_specs"]),
        "authentication": "jupyter_login_required",
        "service_reachable": None,
        "host_attested": False,
        "security_notice": SECURITY_NOTICE,
    }
    if include_paths:
        result["root_dir"] = validated["root_dir"]
        result["public_base_url"] = validated["public_base_url"]
    return result
