"""Read-only Windows probes for notebook startup membership and failure handling."""

import base64
import json
import re
import subprocess
import sys
import uuid
from pathlib import Path

import pytest


pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="Windows native APIs")
INSTALLER = Path(__file__).resolve().parents[1] / "tools" / "install_notebook_startup.ps1"

EXTRACT_FUNCTION = r"""
$tokens = $null
$parseErrors = $null
$ast = [System.Management.Automation.Language.Parser]::ParseFile(
    $scriptPath, [ref]$tokens, [ref]$parseErrors)
$definitions = @($ast.FindAll({
    param($node)
    $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and
        $node.Name -eq 'Get-AnchorNotebookLocalGroupSids'
}, $true))
if ($parseErrors.Count -ne 0 -or $definitions.Count -ne 1) {
    throw 'function_extraction_failed'
}
# Evaluate only the extracted function definition, never the installer body.
. ([scriptblock]::Create($definitions[0].Extent.Text))
"""

CURRENT_LOCAL_USER = r"""
$identity = [Security.Principal.WindowsIdentity]::GetCurrent()
$parts = $identity.Name -split '\\', 2
if ($parts.Count -ne 2 -or $parts[0] -ine $env:COMPUTERNAME) {
    @{ skip = 'requires_current_machine_local_user' } | ConvertTo-Json -Compress
    exit 0
}
$currentUser = $parts[1]
"""


def ps_literal(value):
    return "'" + str(value).replace("'", "''") + "'"


def probe(body, *, extract=False):
    script = (
        "$ErrorActionPreference = 'Stop'\n$ProgressPreference = 'SilentlyContinue'\ntry {\n"
        + "$scriptPath = " + ps_literal(INSTALLER) + "\n"
        + (EXTRACT_FUNCTION if extract else "")
        + body
        + "\n} catch {\n"
        + "Write-Output '{\"probe_failed\":true}'\nexit 2\n}\n"
    )
    encoded = base64.b64encode(script.encode("utf-16-le")).decode("ascii")
    startup = subprocess.STARTUPINFO()
    startup.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    startup.wShowWindow = subprocess.SW_HIDE
    try:
        result = subprocess.run(
            ["powershell.exe", "-NoLogo", "-NoProfile", "-NonInteractive",
             "-ExecutionPolicy", "Bypass", "-EncodedCommand", encoded],
            shell=False, startupinfo=startup, creationflags=subprocess.CREATE_NO_WINDOW,
            capture_output=True, text=True, encoding="utf-8-sig", errors="replace",
            timeout=30, check=False,
        )
    except subprocess.TimeoutExpired:
        pytest.fail("PowerShell probe exceeded 30 seconds", pytrace=False)
    except OSError:
        pytest.fail("PowerShell probe could not start", pytrace=False)
    if result.returncode != 0:
        # Never surface subprocess bodies, native errors, or identity information.
        pytest.fail("PowerShell probe failed (exit %s)" % result.returncode, pytrace=False)
    try:
        data = json.loads(result.stdout)
    except (ValueError, TypeError):
        pytest.fail("PowerShell probe did not return a JSON receipt", pytrace=False)
    if data.get("skip"):
        pytest.skip(data["skip"])
    return data


def test_native_local_memberships_repeat_and_missing_user_fails_closed():
    missing_user = "AnchorNo" + uuid.uuid4().hex[:8]
    data = probe(
        CURRENT_LOCAL_USER
        + "$missingUser = " + ps_literal(missing_user) + "\n"
        + r"""
$first = @(Get-AnchorNotebookLocalGroupSids -UserName $currentUser)
$second = @(Get-AnchorNotebookLocalGroupSids -UserName $currentUser)
foreach ($sid in $first + $second) {
    $parsed = [Security.Principal.SecurityIdentifier]::new($sid)
    if ($parsed.Value -ne $sid) { throw 'invalid_group_sid' }
}
$missingFailed = $false
try {
    $ignored = @(Get-AnchorNotebookLocalGroupSids -UserName $missingUser)
} catch {
    $missingFailed = $_.Exception.Message -eq 'account_group_membership_lookup_failed'
}
@{ first = $first; second = $second; missing_failed = $missingFailed } |
    ConvertTo-Json -Compress -Depth 4
""",
        extract=True,
    )
    assert data["first"]
    assert all(isinstance(sid, str) and re.fullmatch(r"S-\d+(?:-\d+)+", sid)
               for sid in data["first"])
    assert sorted(data["first"]) == sorted(data["second"])
    assert data["missing_failed"] is True
    # Token role checks omit deny-only memberships under UAC; the native account
    # query must retain those memberships regardless of the caller's elevation.


def test_group_sid_resolution_error_fails_closed():
    data = probe(
        CURRENT_LOCAL_USER
        + r"""
$script:lookupAttempted = $false
function Get-LocalGroup {
    [CmdletBinding()]
    param([string]$Name)
    $script:lookupAttempted = $true
    throw 'synthetic_group_lookup_failure'
}
$failedClosed = $false
try {
    $ignored = @(Get-AnchorNotebookLocalGroupSids -UserName $currentUser)
} catch {
    $failedClosed = $_.Exception.Message -eq 'synthetic_group_lookup_failure'
}
@{ lookup_attempted = $script:lookupAttempted; failed_closed = $failedClosed } |
    ConvertTo-Json -Compress
""",
        extract=True,
    )
    assert data["lookup_attempted"] is True
    assert data["failed_closed"] is True


def test_invalid_account_exit_preserves_outer_after_and_finally():
    data = probe(r"""
$after = $false
$finallyRan = $false
$code = $null
$childOutput = @()
$invalidArgs = @{
    Action = 'Plan'
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
@{ exit_code = $code; after = $after; finally_ran = $finallyRan;
   ok = $child.ok; error = $child.error; task_may_exist = $child.task_may_exist } |
    ConvertTo-Json -Compress
""")
    assert data == {
        "exit_code": 1, "after": True, "finally_ran": True,
        "ok": False, "error": "exact_local_account_required", "task_may_exist": False,
    }
