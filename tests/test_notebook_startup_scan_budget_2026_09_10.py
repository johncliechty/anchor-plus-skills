"""Exercise the actual bounded scan guard with counts, without filesystem trees."""

import base64
import json
import subprocess
import sys
from pathlib import Path

import pytest


pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="Windows PowerShell")
INSTALLER = Path(__file__).resolve().parents[1] / "tools" / "install_notebook_startup.ps1"

PROBE = r"""
$tokens = $null
$parseErrors = $null
$ast = [System.Management.Automation.Language.Parser]::ParseFile(
    $scriptPath, [ref]$tokens, [ref]$parseErrors)
if ($parseErrors.Count) { throw 'startup_parse_failed' }
$parameters = @($ast.ParamBlock.Parameters | Where-Object {
    $_.Name.VariablePath.UserPath -eq 'MaxCodeEntries'
})
$guards = @($ast.FindAll({
    param($node)
    $node -is [System.Management.Automation.Language.IfStatementAst] -and
        $node.Clauses.Count -eq 1 -and
        $node.Clauses[0].Item1.Extent.Text -eq '$seen.Count -gt $MaxCodeEntries'
}, $true))
$trackers = @($ast.FindAll({
    param($node)
    $node -is [System.Management.Automation.Language.AssignmentStatementAst] -and
        $node.Left.Extent.Text -eq '$script:codeEntriesChecked' -and
        $node.Right.Extent.Text -eq '$seen.Count'
}, $true))
$failDefinitions = @($ast.FindAll({
    param($node)
    $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and
        $node.Name -eq 'Fail'
}, $true))
if ($parameters.Count -ne 1 -or $guards.Count -ne 1 -or
    $trackers.Count -ne 1 -or $failDefinitions.Count -ne 1 -or
    $trackers[0].Extent.EndOffset -ge $guards[0].Extent.StartOffset) {
    throw 'scan_guard_extraction_failed'
}
# Evaluate only the production parameter, Fail function, count update, and guard.
$parameterBinder = [scriptblock]::Create(
    'param(' + $parameters[0].Extent.Text + ')' + [Environment]::NewLine + '$MaxCodeEntries')
. ([scriptblock]::Create($failDefinitions[0].Extent.Text))
$guardBlock = [scriptblock]::Create(
    $trackers[0].Extent.Text + [Environment]::NewLine + $guards[0].Extent.Text)
$defaultLimit = & $parameterBinder
$invalidLimits = @(foreach ($requested in @(29999, 500001)) {
    $rejected = $false
    try {
        $ignored = & $parameterBinder $requested
    } catch {
        $rejected = $_.Exception.GetType().FullName -eq
            'System.Management.Automation.ParameterBindingValidationException' -and
            $_.Exception.ParameterName -eq 'MaxCodeEntries'
    }
    @{ requested = $requested; rejected = $rejected }
})
$boundaries = @(
    @{ limit = $defaultLimit; count = 30001 },
    @{ limit = 30000; count = 30000 },
    @{ limit = 30000; count = 30001 },
    @{ limit = $defaultLimit; count = ($defaultLimit + 1) },
    @{ limit = 500000; count = 500000 },
    @{ limit = 500000; count = 500001 }
)
$results = @(foreach ($boundary in $boundaries) {
    $MaxCodeEntries = & $parameterBinder $boundary.limit
    $seen = [pscustomobject]@{ Count = $boundary.count }
    $script:codeEntriesChecked = -1
    $script:failure = 'unset'
    $blocked = $false
    $errorCorrect = $true
    try {
        & $guardBlock
    } catch {
        $blocked = $true
        $errorCorrect = $_.Exception.Message -eq 'code_tree_scan_limit_exceeded' -and
            $script:failure -eq 'code_tree_scan_limit_exceeded'
    }
    @{ limit = $MaxCodeEntries; count = $boundary.count; blocked = $blocked;
       tracked = $script:codeEntriesChecked; error_correct = $errorCorrect }
})
@{ default_limit = $defaultLimit; invalid_limits = $invalidLimits; results = $results } |
    ConvertTo-Json -Compress -Depth 4
"""


def test_actual_scan_budget_accepts_large_runtime_and_remains_bounded():
    path_literal = "'" + str(INSTALLER).replace("'", "''") + "'"
    script = (
        "$ErrorActionPreference = 'Stop'\ntry {\n$scriptPath = "
        + path_literal + "\n" + PROBE + "\n} catch { exit 2 }\n"
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
        pytest.fail("Scan budget probe exceeded 30 seconds", pytrace=False)
    except OSError:
        pytest.fail("Scan budget probe could not start", pytrace=False)
    if result.returncode != 0:
        pytest.fail("Scan budget probe failed (exit %s)" % result.returncode, pytrace=False)
    try:
        data = json.loads(result.stdout)
    except ValueError:
        pytest.fail("Scan budget probe returned invalid JSON", pytrace=False)
    assert data["default_limit"] == 200000
    assert data["invalid_limits"] == [
        {"requested": 29999, "rejected": True},
        {"requested": 500001, "rejected": True},
    ]
    assert [(row["limit"], row["count"], row["blocked"]) for row in data["results"]] == [
        (200000, 30001, False), (30000, 30000, False), (30000, 30001, True),
        (200000, 200001, True), (500000, 500000, False), (500000, 500001, True),
    ]
    assert all(row["tracked"] == row["count"] and row["error_correct"]
               for row in data["results"])
