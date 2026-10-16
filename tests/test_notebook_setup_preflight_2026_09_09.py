"""Execute isolated wizard functions; never perform installation or account writes."""
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

pytestmark = pytest.mark.skipif(os.name != 'nt', reason='Windows setup functions')
SCRIPT = Path(__file__).resolve().parents[1] / 'tools' / 'setup_notebooks.ps1'


def run_ps(tmp_path, body):
    harness = tmp_path / 'harness.ps1'
    harness.write_text("$ErrorActionPreference='Stop'\n" + body, encoding='utf-8-sig')
    return subprocess.run(['powershell.exe', '-NoProfile', '-NonInteractive', '-File', str(harness)],
                          capture_output=True, text=True, encoding='utf-8-sig', timeout=30,
                          creationflags=subprocess.CREATE_NO_WINDOW)


def test_both_installer_scripts_parse(tmp_path):
    body = """
$errorsFound = @()
foreach ($file in @('%s','%s')) {
    $tokens=$null; $parseErrors=$null
    $null=[Management.Automation.Language.Parser]::ParseFile($file,[ref]$tokens,[ref]$parseErrors)
    $errorsFound += @($parseErrors)
}
if ($errorsFound.Count) { throw 'Installer PowerShell parse error' }
""" % (str(SCRIPT).replace("'", "''"), str(SCRIPT.with_name('install_notebook_startup.ps1')).replace("'", "''"))
    result=run_ps(tmp_path,body)
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize('version,allowed', [([3,10],False),([3,11],False),([3,12],True),([3,13],True)])
def test_actual_version_preflight_refuses_old_python_before_writes(tmp_path,version,allowed):
    source=SCRIPT.read_text(encoding='utf-8-sig')
    start=source.index('$basePythonVersion =')
    stop=source.index('$r = $null;',start)
    # Evaluate the exact shipped preflight with only its interpreter reply replaced.
    body="function Native { '%s' }\n$basePython='synthetic'\ntry {\n%s\n'allowed'\n} catch { 'refused' }" % (json.dumps(version),source[start:stop])
    result=run_ps(tmp_path,body)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == ('allowed' if allowed else 'refused')


def test_native_timeout_argument_stops_only_its_child(tmp_path):
    body="""
$tokens=$null; $parseErrors=$null
$ast=[Management.Automation.Language.Parser]::ParseFile('%s',[ref]$tokens,[ref]$parseErrors)
$native=$ast.Find({param($node) $node -is [Management.Automation.Language.FunctionDefinitionAst] -and $node.Name -eq 'Native'},$true)
Invoke-Expression $native.Extent.Text
$timer=[Diagnostics.Stopwatch]::StartNew()
try {
    $null=Native '%s' @('-I','-S','-c','"import time; time.sleep(20)"') '' 100
    throw 'Timeout was not applied'
} catch {
    if ($_.Exception.Message -notlike 'Notebook setup dependency timed out*') { throw }
    if ($timer.Elapsed.TotalSeconds -gt 10) { throw 'Timeout was not bounded' }
}
'bounded-timeout'
""" % (str(SCRIPT).replace("'", "''"),sys.executable.replace("'", "''"))
    result=run_ps(tmp_path,body)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == 'bounded-timeout'
