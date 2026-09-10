"""Windows checks for the read-only startup validation action and its boundary."""

import base64
import json
import subprocess
import sys
from pathlib import Path

import pytest


pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="Windows PowerShell")
INSTALLER = Path(__file__).resolve().parents[1] / "tools" / "install_notebook_startup.ps1"


def probe(body):
    path_literal = "'" + str(INSTALLER).replace("'", "''") + "'"
    script = (
        "$ErrorActionPreference = 'Stop'\n$ProgressPreference = 'SilentlyContinue'\ntry {\n"
        + "$scriptPath = " + path_literal + "\n" + body
        + "\n} catch { exit 2 }\n"
    )
    startup = subprocess.STARTUPINFO()
    startup.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    startup.wShowWindow = subprocess.SW_HIDE
    try:
        result = subprocess.run(
            ["powershell.exe", "-NoLogo", "-NoProfile", "-NonInteractive",
             "-ExecutionPolicy", "Bypass", "-EncodedCommand",
             base64.b64encode(script.encode("utf-16-le")).decode("ascii")],
            shell=False, startupinfo=startup, creationflags=subprocess.CREATE_NO_WINDOW,
            capture_output=True, text=True, encoding="utf-8-sig", errors="replace",
            timeout=30, check=False,
        )
    except subprocess.TimeoutExpired:
        pytest.fail("Startup validation probe exceeded 30 seconds", pytrace=False)
    except OSError:
        pytest.fail("Startup validation probe could not start", pytrace=False)
    if result.returncode != 0:
        pytest.fail("Startup validation probe failed (exit %s)" % result.returncode, pytrace=False)
    try:
        return json.loads(result.stdout)
    except ValueError:
        pytest.fail("Startup validation probe returned invalid JSON", pytrace=False)


def test_validate_rejects_invalid_account_without_reaching_credentials():
    data = probe(r"""
function Get-Credential { throw 'credential_tripwire' }
function Register-ScheduledTask { throw 'registration_tripwire' }
$after = $false
$finallyRan = $false
$invalidArgs = @{
    Action = 'Validate'
    PythonExecutable = 'Z:\missing\python.exe'
    ServiceScript = 'Z:\missing\notebook_service.py'
    SettingsFile = 'Z:\missing\settings.json'
    Account = 'invalid'
}
try {
    $childOutput = @(& $scriptPath @invalidArgs)
    $code = $LASTEXITCODE
    $after = $true
} finally {
    $finallyRan = $true
}
$child = ($childOutput -join [Environment]::NewLine) | ConvertFrom-Json -ErrorAction Stop
@{ child = $child; exit_code = $code; after = $after; finally_ran = $finallyRan } |
    ConvertTo-Json -Compress -Depth 4
""")
    assert data["exit_code"] == 1
    assert data["after"] is True
    assert data["finally_ran"] is True
    assert data["child"]["ok"] is False
    assert data["child"]["error"] == "exact_local_account_required"
    assert data["child"]["validation_path"] is None
    assert data["child"]["task_may_exist"] is False
    assert data["child"]["readiness"] == "not_proven"


def test_validate_returns_after_checks_and_before_credential_or_registration():
    data = probe(r"""
$tokens = $null
$parseErrors = $null
$ast = [System.Management.Automation.Language.Parser]::ParseFile(
    $scriptPath, [ref]$tokens, [ref]$parseErrors)
if ($parseErrors.Count) { throw 'startup_parse_failed' }
$validateBranches = @($ast.FindAll({
    param($node)
    $node -is [System.Management.Automation.Language.IfStatementAst] -and
        $node.Clauses.Count -eq 1 -and
        $node.Clauses[0].Item1.Extent.Text -eq '$Action -eq ''Validate'''
}, $true))
if ($validateBranches.Count -ne 1) { throw 'validate_branch_not_unique' }
$branch = $validateBranches[0]
$walks = @($ast.FindAll({
    param($node)
    $node -is [System.Management.Automation.Language.WhileStatementAst] -and
        $node.Condition.Extent.Text.Contains('$pending.Count')
}, $true))
$refusals = @($ast.FindAll({
    param($node)
    $node -is [System.Management.Automation.Language.CommandAst] -and
        $node.GetCommandName() -eq 'Fail' -and $node.CommandElements.Count -gt 1 -and
        $node.CommandElements[1].Value -eq 'task_already_exists_no_overwrite'
}, $true))
$credentials = @($ast.FindAll({
    param($node)
    $node -is [System.Management.Automation.Language.CommandAst] -and
        $node.GetCommandName() -eq 'Get-Credential'
}, $true))
$registrations = @($ast.FindAll({
    param($node)
    $node -is [System.Management.Automation.Language.InvokeMemberExpressionAst] -and
        $node.Member.Value -match '^RegisterTask'
}, $true))
$ordered = $walks.Count -gt 0 -and $refusals.Count -eq 1 -and
    $credentials.Count -gt 0 -and $registrations.Count -gt 0
foreach ($before in @($walks) + @($refusals)) {
    $ordered = $ordered -and $before.Extent.EndOffset -lt $branch.Extent.StartOffset
}
foreach ($after in @($credentials) + @($registrations)) {
    $ordered = $ordered -and $after.Extent.StartOffset -gt $branch.Extent.EndOffset
}
# Execute only the success branch with synthetic values. A missing return or
# added credential request trips this probe; the installer body is never loaded.
function Get-Credential { throw 'credential_tripwire' }
function Register-ScheduledTask { throw 'registration_tripwire' }
$Account = 'SYNTHETIC\AnchorFixture'
$TaskName = 'AnchorValidationFixture'
$script:codeEntriesChecked = 30001
$MaxCodeEntries = 200000
$branchBody = ($branch.Clauses[0].Item2.Statements | ForEach-Object {
    $_.Extent.Text
}) -join [Environment]::NewLine
$branchBody += [Environment]::NewLine + "throw 'post_validate_tripwire'"
$branchOutput = @(& ([scriptblock]::Create($branchBody)))
$receipt = ($branchOutput -join [Environment]::NewLine) | ConvertFrom-Json -ErrorAction Stop
@{ ordered = $ordered; receipt = $receipt } | ConvertTo-Json -Compress -Depth 4
""")
    assert data["ordered"] is True
    assert data["receipt"] == {
        "ok": True, "action": "validate", "task_name": "AnchorValidationFixture",
        "account": "SYNTHETIC\\AnchorFixture",
        "readiness": "not_proven", "endpoint_access": "not_verified",
        "code_entries_checked": 30001, "max_code_entries": 200000,
    }
