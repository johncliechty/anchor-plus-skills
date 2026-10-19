# Private session receipt helper, not a shipped installer or credential transcript.
$ErrorActionPreference = 'Stop'
$receiptPath = Join-Path $PSScriptRoot 'local-setup-result-2026-09-09.json'
function Write-SetupReceipt([string]$Status, [int]$Line = 0, [string]$Message = '') {
    $record = @{at=[DateTimeOffset]::UtcNow.ToString('o');status=$Status;pid=$PID;error_line=$Line;message=$Message}
    [IO.File]::WriteAllText($receiptPath, ($record | ConvertTo-Json -Compress), [Text.UTF8Encoding]::new($false))
}
$Host.UI.RawUI.WindowTitle = 'Anchor notebook setup - one-time administrator installation'
Write-SetupReceipt 'running'
Write-Host 'Anchor notebook setup: choose the project folder and enter your Jupyter password only in this window.'
try {
    & 'C:\dev\Anchor\tools\setup_notebooks.ps1' -PythonExecutable 'C:\Users\john\AppData\Local\Programs\Python\Python313\python.exe' -AnchorDataDirectory 'C:\dev\Anchor' -PublicBaseUrl 'https://gwl-server.tailb49f65.ts.net:8448/' -RExecutable 'C:\Users\john\AppData\Local\Programs\R\bin\R.exe' -RLibraryDirectories @('C:\Users\john\AppData\Local\R\win-library\4.6','C:\Users\john\AppData\Local\Programs\R\library') -TailscaleExecutable 'C:\Program Files\Tailscale\tailscale.exe'
    Write-SetupReceipt 'installed_acceptance_pending'
    Write-Host 'Setup finished. Return to Codex while browser and notebook execution are checked.'
} catch {
    # Installer errors deliberately suppress child stdout and secret-bearing diagnostics.
    Write-SetupReceipt 'failed' $_.InvocationInfo.ScriptLineNumber $_.Exception.Message
    Write-Host 'Setup stopped. Leave this window open; Codex will inspect the non-secret receipt before any recovery.' -ForegroundColor Yellow
}
