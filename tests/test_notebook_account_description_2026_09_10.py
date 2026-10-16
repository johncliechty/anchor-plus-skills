"""Bind the shipped account command safely against Windows cmdlet metadata."""

import base64
import json
import subprocess
import sys
from pathlib import Path

import pytest


pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="Windows LocalAccounts")
SETUP = Path(__file__).resolve().parents[1] / "tools" / "setup_notebooks.ps1"
PREFIX = "ANCHOR_DESCRIPTION_RECEIPT="

PROBE = r"""
$tokens = $null
$parseErrors = $null
$ast = [System.Management.Automation.Language.Parser]::ParseFile(
    $scriptPath, [ref]$tokens, [ref]$parseErrors)
if ($parseErrors.Count) { throw 'setup_parse_failed' }
$findCommand = {
    param($node)
    $node -is [System.Management.Automation.Language.CommandAst] -and
        $node.GetCommandName() -eq 'New-LocalUser'
}
$commands = @($ast.FindAll($findCommand, $true))
if ($commands.Count -eq 0) {
    # Provisioning may be an embedded literal; parse its contents without executing it.
    $payloads = @($ast.FindAll({
        param($node)
        $node -is [System.Management.Automation.Language.StringConstantExpressionAst] -and
            $node.Value.Contains('New-LocalUser -Name $AccountName')
    }, $true))
    if ($payloads.Count -ne 1) { throw 'provisioning_payload_not_unique' }
    $ast = [System.Management.Automation.Language.Parser]::ParseInput(
        $payloads[0].Value, [ref]$tokens, [ref]$parseErrors)
    if ($parseErrors.Count) { throw 'provisioning_parse_failed' }
    $commands = @($ast.FindAll($findCommand, $true))
}
if ($commands.Count -ne 1) { throw 'account_command_not_unique' }
$command = $commands[0]
$description = $null
for ($index = 0; $index -lt $command.CommandElements.Count - 1; $index++) {
    $element = $command.CommandElements[$index]
    if ($element -is [System.Management.Automation.Language.CommandParameterAst] -and
        $element.ParameterName -eq 'Description') {
        $literal = $command.CommandElements[$index + 1]
        if ($literal -isnot [System.Management.Automation.Language.StringConstantExpressionAst]) {
            throw 'description_not_literal'
        }
        $description = $literal.Value
    }
}
if ($null -eq $description) { throw 'description_missing' }
$cmdlet = Get-Command New-LocalUser -CommandType Cmdlet -ErrorAction Stop
$metadata = [System.Management.Automation.CommandMetadata]::new($cmdlet)
if (-not $metadata.SupportsShouldProcess -or -not $cmdlet.Parameters.ContainsKey('WhatIf')) {
    throw 'whatif_not_supported'
}
$limits = @($cmdlet.Parameters['Description'].Attributes | Where-Object {
    $_ -is [System.Management.Automation.ValidateLengthAttribute]
})
if ($limits.Count -ne 1) { throw 'description_validation_metadata_missing' }
$oldDescription = 'Dedicated Anchor notebook runtime; no AI credentials'
if ($description.Length -lt $limits[0].MinLength -or
    $description.Length -gt $limits[0].MaxLength -or
    $oldDescription.Length -le $limits[0].MaxLength) {
    throw 'description_length_regression'
}
$AccountName = 'AnchorProbe' + [Guid]::NewGuid().ToString('N').Substring(0, 6)
$fixtureSecure = ConvertTo-SecureString -String 'Synthetic-Account-Fixture-20260910!' -AsPlainText -Force
Set-Variable -Name accountPassword -Value $fixtureSecure
try {
    # Preserve every shipped argument and switch; mandatory WhatIf prevents creation.
    $shipped = $command.Extent.Text + ' -WhatIf -ErrorAction Stop'
    $ignored = & ([scriptblock]::Create($shipped))
    $oldRejected = $false
    try {
        $ignored = & ([scriptblock]::Create($shipped.Replace($description, $oldDescription)))
    } catch {
        $oldRejected = $_.Exception.GetType().FullName -eq 'System.Management.Automation.ParameterBindingValidationException' -and
            $_.Exception.ParameterName -eq 'Description'
    }
} finally {
    $fixtureSecure.Dispose()
    Remove-Variable -Name accountPassword -ErrorAction SilentlyContinue
}
$receipt = @{ description = $description; description_length = $description.Length;
    maximum_length = $limits[0].MaxLength; old_length = $oldDescription.Length;
    old_rejected_before_execution = $oldRejected; shipped_whatif_bound = $true }
Write-Output ('ANCHOR_DESCRIPTION_RECEIPT=' + ($receipt | ConvertTo-Json -Compress))
"""


def test_shipped_account_description_binds_and_previous_literal_is_rejected():
    path_literal = "'" + str(SETUP).replace("'", "''") + "'"
    script = (
        "$ErrorActionPreference = 'Stop'\n$ProgressPreference = 'SilentlyContinue'\ntry {\n"
        + "$scriptPath = " + path_literal + "\n" + PROBE
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
        pytest.fail("Account metadata probe exceeded 30 seconds", pytrace=False)
    except OSError:
        pytest.fail("Account metadata probe could not start", pytrace=False)
    if result.returncode != 0:
        pytest.fail("Account metadata probe failed (exit %s)" % result.returncode, pytrace=False)
    lines = [line[len(PREFIX):] for line in result.stdout.splitlines() if line.startswith(PREFIX)]
    if len(lines) != 1:
        pytest.fail("Account metadata probe returned no unique receipt", pytrace=False)
    try:
        data = json.loads(lines[0])
    except ValueError:
        pytest.fail("Account metadata probe returned invalid JSON", pytrace=False)
    assert data["description"] == "Anchor notebook runtime; no AI credentials"
    assert data["description_length"] <= data["maximum_length"] < data["old_length"]
    assert data["shipped_whatif_bound"] is True
    assert data["old_rejected_before_execution"] is True
