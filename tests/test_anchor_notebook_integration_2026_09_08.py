"""Hermetic notebook work-product integration; no browser or kernel execution.

All files are synthetic and live below pytest's temporary directory. Anchor's
data directory and the user profile are both isolated, and registry writes,
native processes, and direct network connections fail the test if attempted.
"""
import json
from pathlib import Path
import socket
import subprocess
import sys
from types import SimpleNamespace
from urllib.parse import parse_qs, unquote, urlsplit

import pytest

import anchor_notebooks
import deliverables
import effort_history
import notebook_products
import notebook_runtime
import paths
from steward_cockpit import steward_campaign, steward_routes


def _forbidden_side_effect(*args, **kwargs):
    raise AssertionError("Notebook projection/open must not execute code, use the network, or write a competing pin registry.")


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    root = tmp_path / "project"
    data = tmp_path / "anchor-data"
    profile = tmp_path / "profile"
    for directory in (root, data, profile):
        directory.mkdir()
    monkeypatch.setenv("ANCHOR_DATA_DIR", str(data))
    monkeypatch.setenv("USERPROFILE", str(profile))
    monkeypatch.setenv("HOME", str(profile))
    monkeypatch.setattr(paths, "data_dir", lambda *args, **kwargs: data)
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: profile))
    monkeypatch.setattr(effort_history, "list_efforts", lambda *args, **kwargs: [])
    monkeypatch.setattr(effort_history, "record_effort", _forbidden_side_effect)
    monkeypatch.setattr(deliverables, "run_deliverable", _forbidden_side_effect)
    monkeypatch.setattr(subprocess, "Popen", _forbidden_side_effect)
    monkeypatch.setattr(subprocess, "run", _forbidden_side_effect)
    monkeypatch.setattr(subprocess, "check_output", _forbidden_side_effect)
    monkeypatch.setattr(socket, "create_connection", _forbidden_side_effect)
    real_load_config = anchor_notebooks.load_config
    monkeypatch.setattr(anchor_notebooks, "load_config", lambda: None)
    return SimpleNamespace(
        root=root, data=data, profile=profile,
        project_id="synthetic-notebook-project", real_load_config=real_load_config,
    )


def _source(workspace, relative="lessons/lesson one.py"):
    filename = workspace.root / relative
    filename.parent.mkdir(parents=True, exist_ok=True)
    text = "# Synthetic UTF-8 classroom example: π\nprint(1 + 1)\n"
    filename.write_text(text, encoding="utf-8", newline="")
    return relative, text


def _runtime_config(root, **overrides):
    config = {
        "schema_version": 1,
        "enabled": True,
        "public_base_url": "https://notebooks.example.test",
        "root_dir": str(root),
        "execution_host": socket.gethostname(),
        "local_kernel_specs": {
            "python3": [sys.executable, "-m", "ipykernel_launcher", "-f", "{connection_file}"],
        },
    }
    config.update(overrides)
    return config


def _enable_runtime(workspace, monkeypatch, **overrides):
    config = _runtime_config(workspace.root, **overrides)
    monkeypatch.setattr(anchor_notebooks, "load_config", lambda: config)
    return config


def _register(workspace, relative="lessons/lesson one.py", step="2"):
    relative, text = _source(workspace, relative)
    result = notebook_products.register_instructional(
        workspace.root, relative, "Synthetic classroom notebook", step=step,
    )
    assert result["ok"] is True
    return relative, text, result


def _snapshot(directory):
    return {
        filename.relative_to(directory).as_posix(): filename.read_bytes()
        for filename in directory.rglob("*") if filename.is_file()
    }


def _assert_rejected(body, status):
    assert 400 <= status < 500
    assert "__notebook_redirect__" not in body
    assert body.get("ok") is not True
    assert isinstance(body.get("error") or body.get("message"), str)
    assert (body.get("error") or body.get("message")).strip()


@pytest.mark.parametrize("relative,kernel", [("lessons/python lesson.py", "python3"), ("lessons/r lesson.R", "ir")])
def test_instructional_python_and_r_register_as_verbatim_notebooks(workspace, relative, kernel):
    relative, original, result = _register(workspace, relative)
    assert result["source"] == relative
    notebook_relative = Path(relative).with_suffix(".ipynb").as_posix()
    assert result["notebook"] == notebook_relative
    assert result["artifact"]
    assert (workspace.root / relative).read_text(encoding="utf-8") == original
    notebook = json.loads((workspace.root / notebook_relative).read_text(encoding="utf-8"))
    assert notebook["nbformat"] == 4
    assert notebook["metadata"]["kernelspec"]["name"] == kernel
    assert len(notebook["cells"]) == 1
    assert notebook["cells"][0]["cell_type"] == "code"
    source = notebook["cells"][0]["source"]
    assert ("".join(source) if isinstance(source, list) else source) == original
    assert notebook["cells"][0].get("execution_count") is None
    assert not notebook["cells"][0].get("outputs")


def test_read_only_description_does_not_convert_an_unregistered_source(workspace):
    relative, _ = _source(workspace)
    before = _snapshot(workspace.root)
    description = anchor_notebooks.describe(workspace.root, relative)
    assert description["eligible"] is True
    assert description["source"] == relative
    assert description["can_open"] is False
    assert description["can_convert"] is True
    assert _snapshot(workspace.root) == before
    assert not (workspace.root / "DELIVERABLES.md").exists()


@pytest.mark.parametrize("step", ["2", "2. Notebook practice"])
def test_deliverables_reader_preserves_producing_step_and_notebook_product(workspace, step):
    relative, _, result = _register(workspace, step=step)
    document = steward_campaign.read_deliverables(str(workspace.root))
    rows = [item for item in document["items"] if item["path"] == relative]
    assert len(rows) == 1
    assert rows[0]["what"] == "Synthetic classroom notebook"
    assert rows[0]["step"] == step
    product = rows[0]["notebook_product"]
    assert isinstance(product, dict)
    assert product["notebook"] == result["notebook"]
    assert product["source"] == relative


def test_steward_registration_route_creates_the_same_work_product(workspace):
    relative, _ = _source(workspace)
    body, status = steward_routes.api_post(workspace.root, "notebook-register", {
        "source": relative, "what": "Synthetic route notebook", "step": "3", "dir": "",
    })
    assert status == 200
    assert body["ok"] is True
    rows = steward_campaign.read_deliverables(str(workspace.root))["items"]
    row = next(item for item in rows if item["path"] == relative)
    assert row["what"] == "Synthetic route notebook"
    assert row["step"] == "3"
    assert row["notebook_product"]["notebook"].endswith(".ipynb")


def test_configured_open_redirect_targets_the_exact_https_notebook_tab(workspace, monkeypatch):
    relative, _, result = _register(workspace)
    _enable_runtime(workspace, monkeypatch)
    description = anchor_notebooks.describe(workspace.root, relative)
    assert description["can_open"] is True
    assert not description.get("setup_required")
    body, status = steward_routes.api_get(workspace.root, "notebook-open", {"path": relative, "dir": ""})
    assert status == 200
    url = urlsplit(body["__notebook_redirect__"])
    assert url.scheme == "https"
    assert url.netloc == "notebooks.example.test"
    assert unquote(url.path) == "/lab/tree/" + result["notebook"]
    assert not url.query
    assert not url.fragment
    assert url.username is None and url.password is None


def test_unconfigured_notebook_has_a_clear_setup_failure_and_no_live_redirect(workspace):
    relative, _, _ = _register(workspace)
    description = anchor_notebooks.describe(workspace.root, relative)
    assert description["eligible"] is True
    assert description["can_open"] is False
    assert description["setup_required"] is True
    assert isinstance(description["status"], str) and description["status"]
    body, status = steward_routes.api_get(workspace.root, "notebook-open", {"path": relative, "dir": ""})
    assert status == 409
    _assert_rejected(body, status)


def test_notebook_projection_is_stable_read_only_and_does_not_write_a_second_register(workspace):
    relative, _, _ = _register(workspace)
    before = (_snapshot(workspace.root), _snapshot(workspace.data), _snapshot(workspace.profile))
    first = deliverables.list_pinned_deliverables(workspace.root, workspace.project_id)
    second = deliverables.list_pinned_deliverables(workspace.root, workspace.project_id)
    assert len(first) == len(second) == 1
    row = first[0]
    assert row["source"] == "notebook-register"
    assert row["deliverable_type"] == "notebook"
    assert row["artifact_path"] == relative
    assert row["job_id"] and row["job_id"] == second[0]["job_id"]
    after = (_snapshot(workspace.root), _snapshot(workspace.data), _snapshot(workspace.profile))
    assert after == before


@pytest.mark.parametrize("legacy_target,legacy_type", [("lesson.py", "script"), ("lesson.ipynb", "program")])
def test_notebook_projection_deduplicates_old_source_and_notebook_pins(workspace, monkeypatch, legacy_target, legacy_type):
    _register(workspace, "lesson.py")
    legacy = {
        "source": "pinned", "job_id": "synthetic-legacy-pin", "artifact_path": legacy_target,
        "title": "Legacy synthetic pin", "deliverable_type": legacy_type,
    }
    monkeypatch.setattr(effort_history, "list_efforts", lambda *args, **kwargs: [legacy])
    rows = deliverables.list_pinned_deliverables(workspace.root, workspace.project_id)
    assert len(rows) == 1
    assert rows[0]["job_id"] == "synthetic-legacy-pin"
    assert rows[0]["source"] == "notebook-register"
    assert rows[0]["deliverable_type"] == "notebook"
    assert rows[0]["artifact_path"] == "lesson.py"


def test_get_and_launch_projected_source_return_an_anchor_link_without_executing_python(workspace, monkeypatch):
    relative, _, _ = _register(workspace)
    _enable_runtime(workspace, monkeypatch)
    row = deliverables.list_pinned_deliverables(workspace.root, workspace.project_id)[0]
    found = deliverables.get_pinned_deliverable(workspace.root, workspace.project_id, row["job_id"])
    assert found["job_id"] == row["job_id"]
    assert found["deliverable_type"] == "notebook"
    before = _snapshot(workspace.root)
    result = deliverables.launch_deliverable(workspace.root, workspace.project_id, row["job_id"])
    href = urlsplit(result["href"])
    assert not href.scheme and not href.netloc
    assert href.path == "/api/steward/notebook-open"
    query = parse_qs(href.query)
    assert query["pid"] == [workspace.project_id]
    assert query["path"] == [relative]
    assert "token" not in query
    assert _snapshot(workspace.root) == before


@pytest.mark.parametrize("filename", ["lesson.ipynb", "lesson.IPYNB"])
def test_ipynb_type_is_notebook_not_an_executable_script(filename):
    assert deliverables.infer_type(filename) == "notebook"


def test_registered_ipynb_path_itself_uses_the_same_notebook_runtime(workspace, monkeypatch):
    _, _, result = _register(workspace)
    _enable_runtime(workspace, monkeypatch)
    description = anchor_notebooks.describe(workspace.root, result["notebook"])
    assert description["eligible"] is True
    assert description["can_open"] is True
    assert description["notebook"] == result["notebook"]


def test_open_and_registration_reject_source_path_traversal(workspace, monkeypatch):
    outside = workspace.root.parent / "outside.py"
    original = "print('Synthetic outside source must remain untouched')\n"
    outside.write_text(original, encoding="utf-8", newline="")
    _enable_runtime(workspace, monkeypatch)
    body, status = steward_routes.api_get(workspace.root, "notebook-open", {"path": "../outside.py", "dir": ""})
    _assert_rejected(body, status)
    body, status = steward_routes.api_post(workspace.root, "notebook-register", {
        "source": "../outside.py", "what": "Must not be registered", "step": "4", "dir": "",
    })
    _assert_rejected(body, status)
    assert outside.read_text(encoding="utf-8") == original
    assert not outside.with_suffix(".ipynb").exists()
    assert not (workspace.root / "DELIVERABLES.md").exists()


@pytest.mark.parametrize("override", [
    {"schema_version": 999},
    {"public_base_url": "http://notebooks.example.test"},
    {"public_base_url": "https://synthetic-user:synthetic-password@example.com"},
    {"local_kernel_specs": {"python3": ["ssh", "synthetic-other-host", "python"]}},
])
def test_real_runtime_config_loader_rejects_invalid_configuration(workspace, monkeypatch, override):
    relative, _, _ = _register(workspace)
    config = _runtime_config(workspace.root, **override)
    (workspace.data / "notebook-runtime.json").write_text(json.dumps(config), encoding="utf-8")
    monkeypatch.setattr(anchor_notebooks, "load_config", workspace.real_load_config)
    with pytest.raises(notebook_runtime.NotebookRuntimeError) as raised:
        anchor_notebooks.load_config()
    assert raised.value.code == "invalid_config"
    body, status = steward_routes.api_get(workspace.root, "notebook-open", {"path": relative, "dir": ""})
    _assert_rejected(body, status)


def test_runtime_cannot_open_a_project_outside_its_configured_root(workspace, monkeypatch):
    relative, _, _ = _register(workspace)
    other_root = workspace.root.parent / "different-runtime-root"
    other_root.mkdir()
    _enable_runtime(workspace, monkeypatch, root_dir=str(other_root))
    body, status = steward_routes.api_get(workspace.root, "notebook-open", {"path": relative, "dir": ""})
    _assert_rejected(body, status)
