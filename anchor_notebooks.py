"""Shared notebook work-product resolver for Deliverables, Plan and Files.

Private service configuration is installation-local. Artifact descriptions and
companions contain no credentials, project-specific defaults or host URL.
"""
from __future__ import annotations

import json
from pathlib import Path

import paths
import notebook_artifacts as artifacts
import notebook_runtime as runtime


def config_path():
    return paths.data_dir() / "notebook-runtime.json"


def load_config():
    target = config_path()
    if not target.exists():
        return None
    try:
        with target.open("rb") as handle:
            raw = handle.read(65537)
        if len(raw) > 65536:
            raise ValueError("oversized config")
        return runtime.validate_config(json.loads(raw))
    except (ValueError, OSError) as exc:
        raise runtime.NotebookRuntimeError("invalid_config", "The private Jupyter service configuration is invalid; run notebook setup.") from exc


def service_status():
    try:
        return runtime.runtime_status(load_config())
    except runtime.NotebookRuntimeError as exc:
        return {"configured": False, "enabled": False, "status": "invalid", "error": exc.code,
                "message": str(exc), "security_notice": runtime.SECURITY_NOTICE}


def describe(root, relative):
    """Read-only description; never converts or executes a source on a GET."""
    if not isinstance(relative, str) or Path(relative).suffix.lower() not in (".py", ".r", ".ipynb"):
        return None
    result = {"eligible": True, "source": None, "notebook": None,
              "status": "unconverted", "can_open": False, "can_convert": False}
    try:
        kernel = "ir" if Path(relative).suffix.lower() == ".r" else "python3"
        if Path(relative).suffix.lower() == ".ipynb":
            safe = artifacts._path(artifacts._root(root), artifacts._relative(relative))
            if not safe.is_file():
                raise ValueError("Notebook is unavailable")
            document = json.loads(artifacts._read(artifacts._root(root), relative, artifacts.MAX_NOTEBOOK_BYTES))
            if not isinstance(document, dict) or document.get("nbformat") != 4:
                raise ValueError("A valid Jupyter notebook is required")
            kernel = document.get("metadata", {}).get("kernelspec", {}).get("name")
            if kernel not in ("python3", "ir"):
                raise ValueError("Choose an explicitly configured local Python or R kernel for this notebook")
            result.update(notebook=relative, status="standalone")
        else:
            result.update(artifacts.resolve_artifact(root, relative))
            result["can_convert"] = result["status"] == "unconverted"
        config = load_config()
        if config is None:
            result.update(setup_required=True, message="Configure same-host Jupyter to open this notebook.")
        elif result["notebook"]:
            runtime.notebook_url(config, root, result["notebook"])
            if kernel not in config["local_kernel_specs"]:
                result.update(setup_required=True, message="The required local notebook kernel is not configured.")
            else:
                result.update(can_open=True, execution_host=config["execution_host"],
                              message="Opens in Jupyter on the Anchor host; separate Jupyter sign-in may be required.")
    except (ValueError, OSError, TypeError, AttributeError) as exc:
        result.update(can_open=False, message=str(exc), status="unavailable")
    return result


def decorate(root, item):
    info = describe(root, item.get("path"))
    return {**item, "notebook_product": info} if info else item


def open_url(root, relative):
    info = describe(root, relative)
    if not info or not info.get("can_open"):
        raise runtime.NotebookRuntimeError("not_ready", (info or {}).get("message") or "No configured notebook is available for this work product.")
    return runtime.notebook_url(load_config(), root, info["notebook"])


def register(root, *, source, what, step="", regenerate=False):
    from notebook_products import register_instructional
    result = register_instructional(root, source, what, step=step, regenerate=regenerate)
    return {"ok": True, "registration": result, "notebook_product": describe(root, source)}
