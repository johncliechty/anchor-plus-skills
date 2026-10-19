"""Isolated Windows probes for private password retries and resource cleanup."""

import base64
import json
import subprocess
import sys
from pathlib import Path

import pytest


pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="Windows PowerShell")
SETUP = Path(__file__).resolve().parents[1] / "tools" / "setup_notebooks.ps1"

PROBE = r"""
$tokens = $null
$parseErrors = $null
$ast = [System.Management.Automation.Language.Parser]::ParseFile(
    $scriptPath, [ref]$tokens, [ref]$parseErrors)
$definitions = @($ast.FindAll({
    param($node)
    $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and
        $node.Name -eq 'Read-JupyterPasswordHash'
}, $true))
if ($parseErrors.Count -ne 0 -or $definitions.Count -ne 1) { throw 'bad_function_ast' }
$loops = @($definitions[0].Body.FindAll({
    param($node)
    $node -is [System.Management.Automation.Language.WhileStatementAst]
}, $true))
if ($loops.Count -ne 1) { throw 'missing_retry_loop' }
$tries = @($loops[0].Body.FindAll({
    param($node)
    $node -is [System.Management.Automation.Language.TryStatementAst]
}, $true))
if ($tries.Count -ne 1 -or $null -eq $tries[0].Finally) { throw 'missing_cleanup_finally' }
$freeCalls = @($tries[0].Finally.FindAll({
    param($node)
    $node -is [System.Management.Automation.Language.InvokeMemberExpressionAst] -and
        $node.Member.Value -eq 'ZeroFreeBSTR'
}, $true))
$freedVariables = @($freeCalls | ForEach-Object {
    $_.Arguments[0].VariablePath.UserPath
} | Sort-Object)
$cleanupCorrect = $freedVariables.Count -eq 2 -and
    $freedVariables[0] -eq 'confirmPointer' -and $freedVariables[1] -eq 'secretPointer'
# Load only the helper definition, never the setup script or account operations.
. ([scriptblock]::Create($definitions[0].Extent.Text))

$valid = 'Synthetic-Notebook-Cafe12!'
$values = switch ($scenario) {
    'retry' { @('short', 'short', 'CaseSensitive12!', 'casesensitive12!', $valid, $valid) }
    'interrupt' { @($valid) }
    'native_failure' { @($valid, $valid) }
}
$script:pending = [Collections.Generic.Queue[Security.SecureString]]::new()
$allSecrets = @()
foreach ($text in $values) {
    $fixtureSecure = ConvertTo-SecureString -String $text -AsPlainText -Force
    $script:pending.Enqueue($fixtureSecure)
    $allSecrets += $fixtureSecure
}
$script:reads = 0
$script:nativeCalls = 0
$script:messages = @()
$script:stdinCorrect = $true
$script:argumentsSafe = $true
function Read-Host {
    param([string]$Prompt, [switch]$AsSecureString)
    if (-not $AsSecureString) { throw 'nonprivate_prompt' }
    $script:reads++
    if ($scenario -eq 'interrupt' -and $script:reads -eq 2) {
        throw 'synthetic_read_interrupted'
    }
    return $script:pending.Dequeue()
}
function Write-Host {
    param($Object)
    $script:messages += [string]$Object
}
function Native {
    param([string]$Exe, [string[]]$Argv, [string]$Stdin)
    $script:nativeCalls++
    $script:stdinCorrect = [string]::Equals($Stdin, $valid, [StringComparison]::Ordinal)
    $script:argumentsSafe = $Argv.Count -eq 3 -and $Argv[0] -eq '-I' -and
        $Argv[1] -eq '-c' -and
        $Argv[2].Contains("sys.stdin.buffer.read().decode('utf-8')") -and
        -not (($Argv -join ' ').Contains($Stdin))
    if ($scenario -eq 'native_failure') { throw 'synthetic_native_failure' }
    return 'argon2:synthetic-fixture'
}
$returned = $false
$errorCode = $null
try {
    $value = Read-JupyterPasswordHash 'C:\synthetic\python.exe'
    $returned = $value -eq 'argon2:synthetic-fixture'
} catch {
    $errorCode = switch ($_.Exception.Message) {
        'synthetic_read_interrupted' { 'synthetic_read_interrupted' }
        'synthetic_native_failure' { 'synthetic_native_failure' }
        default { 'unexpected_helper_failure' }
    }
}
$disposed = @(foreach ($fixtureSecure in $allSecrets) {
    try {
        $copy = $fixtureSecure.Copy()
        $copy.Dispose()
        $false
    } catch {
        $_.Exception.GetBaseException() -is [ObjectDisposedException]
    }
})
@{ reads = $script:reads; native_calls = $script:nativeCalls;
   returned = $returned; error_code = $errorCode; disposed = $disposed;
   cleanup_finally = $cleanupCorrect; messages = $script:messages;
   stdin_correct = $script:stdinCorrect; arguments_safe = $script:argumentsSafe } |
    ConvertTo-Json -Compress -Depth 4
"""


@pytest.mark.parametrize(
    "scenario, reads, native_calls, returned, error_code, secret_count",
    [
        ("retry", 6, 1, True, None, 6),
        ("interrupt", 2, 0, False, "synthetic_read_interrupted", 1),
        ("native_failure", 2, 1, False, "synthetic_native_failure", 2),
    ],
)
def test_private_password_helper(scenario, reads, native_calls, returned, error_code, secret_count):
    setup_literal = "'" + str(SETUP).replace("'", "''") + "'"
    script = (
        "$ErrorActionPreference = 'Stop'\n$ProgressPreference = 'SilentlyContinue'\ntry {\n"
        + "$scriptPath = " + setup_literal + "\n$scenario = '" + scenario + "'\n"
        + PROBE
        + "\n} catch { Write-Output '{\"probe_failed\":true}'; exit 2 }\n"
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
        pytest.fail("Password helper probe exceeded 30 seconds", pytrace=False)
    except OSError:
        pytest.fail("Password helper probe could not start", pytrace=False)
    if result.returncode != 0:
        pytest.fail("Password helper probe failed (exit %s)" % result.returncode, pytrace=False)
    try:
        data = json.loads(result.stdout)
    except (ValueError, TypeError):
        pytest.fail("Password helper probe returned no JSON receipt", pytrace=False)
    assert data["reads"] == reads
    assert data["native_calls"] == native_calls
    assert data["returned"] is returned
    assert data["error_code"] == error_code
    assert data["disposed"] == [True] * secret_count
    assert data["cleanup_finally"] is True
    assert data["stdin_correct"] is True
    assert data["arguments_safe"] is True
    if scenario == "retry":
        assert len(data["messages"]) == 2
        assert "at least 12 characters" in data["messages"][0]
        assert "including case" in data["messages"][1]
    else:
        assert data["messages"] == []
