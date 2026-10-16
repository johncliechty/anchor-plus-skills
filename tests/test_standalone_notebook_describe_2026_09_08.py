"""Standalone notebook descriptors with synthetic files and pure runtime stubs.

These tests never load the real notebook-service configuration, contact Jupyter,
start a kernel, execute a cell, or read outside their temporary workspace.
"""

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

import anchor_notebooks


def notebook_document(kernel="python3"):
    return {
        "nbformat": 4,
        "nbformat_minor": 5,
        "metadata": {
            "kernelspec": {
                "name": kernel,
                "display_name": "Synthetic Python" if kernel == "python3" else "Synthetic R",
                "language": "python" if kernel == "python3" else "R",
            },
        },
        "cells": [{
            "cell_type": "code", "metadata": {}, "execution_count": None,
            "outputs": [], "source": ["1 + 1\n"],
        }],
    }


@pytest.fixture
def workspace(monkeypatch, tmp_path):
    root = tmp_path / "workspace"
    root.mkdir()
    context = SimpleNamespace(
        root=root,
        config={
            "execution_host": "synthetic-anchor-host",
            "local_kernel_specs": {"python3": ["unused"], "ir": ["unused"]},
        },
        config_reads=[],
        url_calls=[],
    )

    def load_config():
        context.config_reads.append(True)
        return context.config

    def notebook_url(config, supplied_root, relative):
        assert config is context.config
        assert Path(supplied_root).resolve() == root.resolve()
        context.url_calls.append(relative)
        return "https://synthetic-jupyter.example.invalid/lab/tree/" + relative

    monkeypatch.setattr(anchor_notebooks, "load_config", load_config)
    monkeypatch.setattr(anchor_notebooks.runtime, "notebook_url", notebook_url)
    return context


def write_notebook(workspace, name="example.ipynb", *, kernel="python3", document=None):
    path = workspace.root / name
    path.write_text(json.dumps(notebook_document(kernel) if document is None else document), encoding="utf-8")
    return name


@pytest.mark.parametrize("kernel", ["python3", "ir"])
def test_standalone_python_and_r_notebooks_can_open_on_configured_anchor_host(workspace, kernel):
    relative = write_notebook(workspace, f"synthetic-{kernel}.ipynb", kernel=kernel)
    descriptor = anchor_notebooks.describe(workspace.root, relative)
    assert descriptor["eligible"] is True
    assert descriptor["source"] is None
    assert descriptor["notebook"] == relative
    assert descriptor["status"] == "standalone"
    assert descriptor["can_open"] is True
    assert descriptor["can_convert"] is False
    assert descriptor["execution_host"] == "synthetic-anchor-host"
    assert not descriptor.get("setup_required", False)
    assert workspace.url_calls == [relative]


def test_r_notebook_requires_the_configured_local_r_kernel(workspace):
    workspace.config["local_kernel_specs"] = {"python3": ["unused"]}
    relative = write_notebook(workspace, kernel="ir")
    descriptor = anchor_notebooks.describe(workspace.root, relative)
    assert descriptor["status"] == "standalone"
    assert descriptor["notebook"] == relative
    assert descriptor["can_open"] is False
    assert descriptor["can_convert"] is False
    assert descriptor["setup_required"] is True


def test_valid_standalone_notebook_without_service_configuration_requires_setup(workspace):
    workspace.config = None
    relative = write_notebook(workspace)
    descriptor = anchor_notebooks.describe(workspace.root, relative)
    assert descriptor["status"] == "standalone"
    assert descriptor["notebook"] == relative
    assert descriptor["can_open"] is False
    assert descriptor["setup_required"] is True
    assert workspace.url_calls == []


@pytest.mark.parametrize("text", ["{not valid JSON", '{"nbformat":4,"metadata":'])
def test_malformed_or_truncated_notebook_json_never_offers_open(workspace, text):
    relative = "malformed.ipynb"
    (workspace.root / relative).write_text(text, encoding="utf-8")
    descriptor = anchor_notebooks.describe(workspace.root, relative)
    assert descriptor["status"] == "unavailable"
    assert descriptor["can_open"] is False
    assert descriptor.get("message")
    assert workspace.url_calls == []


@pytest.mark.parametrize("metadata", [
    None, [], "invalid metadata", {"kernelspec": None}, {"kernelspec": []},
])
def test_invalid_metadata_shapes_become_unavailable_without_runtime_calls(workspace, metadata):
    document = notebook_document()
    document["metadata"] = metadata
    relative = write_notebook(workspace, document=document)
    descriptor = anchor_notebooks.describe(workspace.root, relative)
    assert descriptor["status"] == "unavailable"
    assert descriptor["can_open"] is False
    assert descriptor.get("message")
    assert workspace.url_calls == []


@pytest.mark.parametrize("kernel", ["remote-python", "gateway-python", "julia", "ir-remote"])
def test_unknown_or_remote_kernel_names_are_not_treated_as_supported_local_kernels(workspace, kernel):
    # A similarly named entry in a mocked configuration must not bypass the
    # standalone artifact's explicit python3/ir eligibility restriction.
    workspace.config["local_kernel_specs"][kernel] = ["unused"]
    relative = write_notebook(workspace, kernel=kernel)
    descriptor = anchor_notebooks.describe(workspace.root, relative)
    assert descriptor["status"] == "unavailable"
    assert descriptor["can_open"] is False
    assert workspace.url_calls == []


@pytest.mark.parametrize("version", [3, "4", None])
def test_only_explicit_notebook_format_four_is_accepted(workspace, version):
    document = notebook_document()
    document["nbformat"] = version
    relative = write_notebook(workspace, document=document)
    descriptor = anchor_notebooks.describe(workspace.root, relative)
    assert descriptor["status"] == "unavailable"
    assert descriptor["can_open"] is False
    assert workspace.url_calls == []


@pytest.mark.parametrize("document", [[], "not a notebook", 4])
def test_top_level_non_object_json_is_not_a_notebook(workspace, document):
    relative = write_notebook(workspace, document=document)
    descriptor = anchor_notebooks.describe(workspace.root, relative)
    assert descriptor["status"] == "unavailable"
    assert descriptor["can_open"] is False
    assert workspace.url_calls == []


def test_missing_standalone_notebook_never_produces_a_live_link(workspace):
    descriptor = anchor_notebooks.describe(workspace.root, "missing.ipynb")
    assert descriptor["status"] == "unavailable"
    assert descriptor["can_open"] is False
    assert workspace.url_calls == []


@pytest.mark.parametrize("escape_kind", ["parent", "backslash_parent", "absolute"])
def test_paths_outside_the_project_are_rejected_before_artifact_read(workspace, monkeypatch, escape_kind):
    outside = workspace.root.parent / "outside.ipynb"
    outside.write_text(json.dumps(notebook_document()), encoding="utf-8")
    relative = {
        "parent": "../outside.ipynb",
        "backslash_parent": "..\\outside.ipynb",
        "absolute": str(outside.resolve()),
    }[escape_kind]
    read_calls = []
    original_read = anchor_notebooks.artifacts._read

    def read(*args, **kwargs):
        read_calls.append((args, kwargs))
        return original_read(*args, **kwargs)

    monkeypatch.setattr(anchor_notebooks.artifacts, "_read", read)
    descriptor = anchor_notebooks.describe(workspace.root, relative)
    assert descriptor["status"] == "unavailable"
    assert descriptor["can_open"] is False
    assert read_calls == []
    assert workspace.url_calls == []


@pytest.mark.parametrize("relative", [None, 42, "notes.txt", "lesson.html"])
def test_non_notebook_and_non_script_inputs_are_not_eligible(workspace, relative):
    assert anchor_notebooks.describe(workspace.root, relative) is None
    assert workspace.config_reads == []
    assert workspace.url_calls == []
