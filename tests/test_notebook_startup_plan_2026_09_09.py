"""Read-only Windows startup-plan canaries using synthetic local fixtures.

Only Action Plan is invoked: never Install, account setup, UAC, or a service.
These tests do not prove account ACLs, endpoint access, or runtime readiness.
"""

import json
import os
from pathlib import Path
import shlex
import socket
import subprocess
import sys
import xml.etree.ElementTree as ET

import pytest


pytestmark = pytest.mark.skipif(os.name != "nt", reason="Windows Task Scheduler plan only")
SCRIPT = Path(__file__).resolve().parents[1] / "tools" / "install_notebook_startup.ps1"
NS = {"t": "http://schemas.microsoft.com/windows/2004/02/mit/task"}
SYNTHETIC_HASH = "argon2:$argon2id$v=19$m=10240,t=10,p=8$c3ludGhldGljc2FsdA$c3ludGhldGljaGFzaA"


@pytest.fixture
def planned_install(tmp_path):
    workspace = tmp_path / "workspace"
    application = tmp_path / "app"
    private = tmp_path / "private"
    for directory in (workspace, application, private):
        directory.mkdir()
    service_script = application / "notebook_service.py"
    service_script.write_text("raise SystemExit('Plan must not execute this synthetic service')\n", encoding="utf-8")
    (workspace / "preserve.txt").write_text("Synthetic workspace: preserve exactly.\n", encoding="utf-8")
    password = private / "password.json"
    password.write_text(json.dumps({"IdentityProvider": {"hashed_password": SYNTHETIC_HASH}}), encoding="utf-8")
    account = socket.gethostname() + "\\SyntheticNotebook"
    settings = {
        "runtime": {
            "schema_version": 1,
            "enabled": True,
            "public_base_url": "https://notebooks.example.test/",
            "root_dir": str(workspace),
            "execution_host": socket.gethostname(),
            "local_kernel_specs": {
                "python3": [sys.executable, "-m", "ipykernel_launcher", "-f", "{connection_file}"]
            },
        },
        "service": {
            "runtime_dir": str(private),
            "password_file": str(password),
            "service_account": account,
            "dedicated_account_confirmed": True,
            "listen_host": "127.0.0.1",
            "port": 8891,
            "runtime_paths": [],
            "r_library_dirs": [],
        },
    }
    settings_file = private / "settings.json"
    settings_file.write_text(json.dumps(settings), encoding="utf-8")
    return {
        "root": tmp_path,
        "workspace": workspace,
        "script": service_script,
        "settings_file": settings_file,
        "settings": settings,
        "account": account,
    }


def _snapshot(root):
    # This is only the small synthetic fixture tree, never a project scan.
    return {
        str(path.relative_to(root)): None if path.is_dir() else path.read_bytes()
        for path in root.rglob("*")
    }


def _plan(fixture, *, account=None):
    before = _snapshot(fixture["root"])
    result = subprocess.run(
        [
            "powershell.exe", "-NoProfile", "-NonInteractive", "-File", str(SCRIPT),
            "-Action", "Plan",
            "-PythonExecutable", sys.executable,
            "-ServiceScript", str(fixture["script"]),
            "-SettingsFile", str(fixture["settings_file"]),
            "-Account", account if account is not None else fixture["account"],
        ],
        cwd=fixture["root"],
        capture_output=True,
        text=True,
        encoding="utf-8-sig",
        timeout=30,
        check=False,
    )
    assert _snapshot(fixture["root"]) == before
    return result, json.loads(result.stdout)


def test_plan_is_read_only_disabled_and_uses_direct_isolated_python(planned_install):
    result, document = _plan(planned_install)
    assert result.returncode == 0, result.stderr
    assert document["ok"] is True
    assert document["action"] == "plan"
    assert document["account"] == planned_install["account"]
    assert Path(document["workspace"]) == planned_install["workspace"]
    assert document["registration_disabled_until_verified"] is True
    assert document["account_acl_checks"] == "deferred_to_install"
    assert document["endpoint_access"] == "not_verified"
    assert document["readiness"] == "not_proven"

    xml = document["task_xml"]
    task = ET.fromstring(xml)
    assert task.tag == "{" + NS["t"] + "}Task"
    actions = task.find("t:Actions", NS)
    assert actions is not None and len(actions) == 1
    action = actions.find("t:Exec", NS)
    assert action is not None
    assert Path(action.findtext("t:Command", namespaces=NS)) == Path(sys.executable)
    # Fixture paths cannot contain quote characters; non-POSIX tokenization
    # preserves their Windows backslashes while accepting quoted paths.
    arguments = [part[1:-1] if part.startswith('"') and part.endswith('"') else part
                 for part in shlex.split(action.findtext("t:Arguments", namespaces=NS), posix=False)]
    assert len(arguments) == 4
    assert arguments[0] == "-I"
    assert Path(arguments[1]) == planned_install["script"]
    assert arguments[2] == "--settings"
    assert Path(arguments[3]) == planned_install["settings_file"]

    principal = task.find("t:Principals/t:Principal", NS)
    assert principal is not None and principal.attrib["id"] == "NotebookAccount"
    assert principal.findtext("t:UserId", namespaces=NS) == planned_install["account"]
    assert principal.findtext("t:LogonType", namespaces=NS) == "Password"
    assert principal.findtext("t:RunLevel", namespaces=NS) == "LeastPrivilege"
    assert task.findtext("t:Triggers/t:BootTrigger/t:Delay", namespaces=NS) == "PT20S"
    assert task.findtext("t:Settings/t:Enabled", namespaces=NS) == "false"
    assert task.findtext("t:Settings/t:MultipleInstancesPolicy", namespaces=NS) == "IgnoreNew"
    assert task.findtext("t:Settings/t:ExecutionTimeLimit", namespaces=NS) == "PT0S"
    assert task.findtext("t:Settings/t:RestartOnFailure/t:Count", namespaces=NS) == "3"
    assert SYNTHETIC_HASH not in result.stdout
    assert "hashed_password" not in result.stdout
    assert task.find(".//t:Password", NS) is None


def test_task_scheduler_accepts_plan_schema_without_registration(planned_install):
    result, document = _plan(planned_install)
    assert result.returncode == 0
    # NewTask creates an in-memory definition only. Never call RegisterTask,
    # RegisterTaskDefinition, Run, or any account/credential operation here.
    check = subprocess.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command",
         "$ErrorActionPreference='Stop'; $scheduler=New-Object -ComObject Schedule.Service; "
         "$scheduler.Connect(); $definition=$scheduler.NewTask(0); "
         "$definition.XmlText=[Console]::In.ReadToEnd(); Write-Output 'schema-valid'"],
        input=document["task_xml"], capture_output=True, text=True, timeout=30,
    )
    assert check.returncode == 0, check.stderr
    assert check.stdout.strip() == "schema-valid"


@pytest.mark.parametrize("invalid", ["wrong_host_account", "workspace_overlap"])
def test_invalid_plan_refuses_registration_and_still_proves_no_readiness(planned_install, invalid):
    account = None
    if invalid == "wrong_host_account":
        account = socket.gethostname() + "-OtherHost\\SyntheticNotebook"
        expected = "exact_local_account_required"
    else:
        # The existing parent now contains both service code and private state.
        planned_install["settings"]["runtime"]["root_dir"] = str(planned_install["root"])
        planned_install["settings_file"].write_text(json.dumps(planned_install["settings"]), encoding="utf-8")
        expected = "service_paths_must_be_outside_workspace"
    result, document = _plan(planned_install, account=account)
    assert result.returncode != 0
    assert document["ok"] is False
    assert document["error"] == expected
    assert document["readiness"] == "not_proven"
    assert document["task_may_exist"] is False
