# Private, single-use recovery of this session's unprovisioned runtime preparation.
$ErrorActionPreference = 'Stop'
$receiptPath = Join-Path $PSScriptRoot 'account-setup-result-2026-09-10.json'
# This refusal is deliberately outside every result-writing catch.
if (Test-Path -LiteralPath $receiptPath) {
    Write-Host 'This attempt already has a result. It was preserved; no setup action was taken.' -ForegroundColor Yellow
    Write-Host ('Result: ' + $receiptPath)
    return
}
$retainedPath = $null
$phase = 'validating_failed_preparation'
function Write-SetupReceipt([string]$Status, $Failure=$null) {
    $record = @{at=[DateTimeOffset]::UtcNow.ToString('o'); status=$Status; phase=$phase; pid=$PID; retained_preparation=$retainedPath}
    if ($null -ne $Failure) {
        # Record identifiers and source location, never invocation arguments or locals.
        $record.error_type = $Failure.Exception.GetType().FullName
        $record.error_id = $Failure.FullyQualifiedErrorId
        $record.error_script = $Failure.InvocationInfo.ScriptName
        $record.error_line = $Failure.InvocationInfo.ScriptLineNumber
    }
    [IO.File]::WriteAllText($receiptPath,($record | ConvertTo-Json -Compress),[Text.UTF8Encoding]::new($false))
}
$Host.UI.RawUI.WindowTitle = 'Anchor notebook installation - corrected account setup'
try {
    $admin = [Security.Principal.WindowsPrincipal]::new([Security.Principal.WindowsIdentity]::GetCurrent())
    if (-not $admin.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) { throw 'Run this recovery as administrator.' }
    if ($PID -ne 23240) { throw 'Use the existing administrator window from this installation.' }
    $old = Get-CimInstance Win32_Process -Filter 'ProcessId=23240'
    if ($null -eq $old -or $old.Name -ine 'powershell.exe' -or $old.CommandLine -notlike '*launch-local-setup-fixed-folder-2026-09-09.ps1*') { throw 'Original installer window identity changed.' }
    Write-SetupReceipt 'validating_failed_preparation'
    $prior = Get-Content -LiteralPath (Join-Path $PSScriptRoot 'password-recovery-result-2026-09-09.json') -Raw -Encoding UTF8 | ConvertFrom-Json
    if ($prior.status -ne 'failed' -or $prior.pid -ne 23240 -or $prior.message -ne 'Recovery already has a receipt; inspect before any further action.') { throw 'Expected inspected recovery receipt was not confirmed.' }
    if (@(Get-LocalUser | Where-Object { $_.Name -ieq 'AnchorNotebook' }).Count) { throw 'Notebook account exists; recovery refused.' }
    if (@(Get-ScheduledTask | Where-Object { $_.TaskName -eq 'AnchorNotebookHost' }).Count) { throw 'Notebook task exists; recovery refused.' }
    if (Test-Path -LiteralPath 'C:\dev\Anchor\notebook-runtime.json') { throw 'Notebook runtime configuration exists; recovery refused.' }
    $setup = 'C:\dev\Anchor\tools\setup_notebooks.ps1'
    $verified = Get-Content -LiteralPath (Join-Path $PSScriptRoot 'account-setup-verified-source-2026-09-10.json') -Raw -Encoding UTF8 | ConvertFrom-Json
    if ($verified.status -ne 'passed' -or (Get-FileHash -LiteralPath $setup -Algorithm SHA256).Hash -ine $verified.sha256) { throw 'Installer must match its verified source.' }
    $install = [IO.Path]::GetFullPath('C:\ProgramData\AnchorNotebook')
    $item = Get-Item -LiteralPath $install -Force
    if (-not $item.PSIsContainer -or $item.FullName -ine $install -or ($item.Attributes -band [IO.FileAttributes]::ReparsePoint)) { throw 'Expected owned installation directory required.' }
    $ancestor = $item.Parent
    while ($null -ne $ancestor) {
        if ($ancestor.Attributes -band [IO.FileAttributes]::ReparsePoint) { throw 'Reparse ancestor refused.' }
        $ancestor = $ancestor.Parent
    }
    $entries = @(Get-ChildItem -LiteralPath $install -Force)
    if ($entries.Count -ne 2 -or @($entries | Where-Object { $_.Name -notin @('python','preparation.json') -or ($_.Attributes -band [IO.FileAttributes]::ReparsePoint) }).Count) { throw 'Unexpected installation state; recovery refused.' }
    if (-not (Get-Item -LiteralPath (Join-Path $install 'python') -Force).PSIsContainer -or (Get-Item -LiteralPath (Join-Path $install 'preparation.json') -Force).PSIsContainer) { throw 'Preparation entry types do not match.' }
    $preparation = Get-Content -LiteralPath (Join-Path $install 'preparation.json') -Raw -Encoding UTF8 | ConvertFrom-Json
    if ($preparation.schema_version -ne 1 -or $preparation.status -ne 'runtime_preparation' -or $preparation.workspace -ine 'C:\dev\Teaching' -or $preparation.base_python -ine 'C:\Users\john\AppData\Local\Programs\Python\Python313\python.exe') { throw 'Preparation manifest does not match this authorized attempt.' }
    $retainedPath = [IO.Path]::GetFullPath('C:\ProgramData\AnchorNotebook-failed-account-' + [DateTime]::UtcNow.ToString('yyyyMMddTHHmmssZ'))
    if ([IO.Path]::GetDirectoryName($retainedPath) -ine 'C:\ProgramData' -or [IO.Path]::GetFileName($retainedPath) -notmatch '^AnchorNotebook-failed-account-\d{8}T\d{6}Z$' -or (Test-Path -LiteralPath $retainedPath)) { throw 'Fresh exact recovery destination required.' }
    # Both absolute paths are verified software locations; Teaching is untouched.
    $phase = 'retaining_failed_preparation'
    Write-SetupReceipt 'retaining_failed_preparation'
    Move-Item -LiteralPath $install -Destination $retainedPath
    $phase = 'installing'
    Write-SetupReceipt 'installing'
    Write-Host 'Software: C:\ProgramData\AnchorNotebook. Notebooks: C:\dev\Teaching.'
    Write-Host 'Preparing notebook software. Then enter your chosen password twice (at least 12 characters).'
    function Read-Host([string]$Prompt, [switch]$AsSecureString) {
        if (-not $AsSecureString) { throw 'Only a secure local prompt is expected.' }
        Write-SetupReceipt 'awaiting_private_password'
        $localSecret = Microsoft.PowerShell.Utility\Read-Host -Prompt $Prompt -AsSecureString
        Write-SetupReceipt 'installing'
        return $localSecret
    }
    & $setup -PythonExecutable 'C:\Users\john\AppData\Local\Programs\Python\Python313\python.exe' -AnchorDataDirectory 'C:\dev\Anchor' -PublicBaseUrl 'https://gwl-server.tailb49f65.ts.net:8448/' -NotebookRoot 'C:\dev\Teaching' -RExecutable 'C:\Users\john\AppData\Local\Programs\R\bin\R.exe' -RLibraryDirectories @('C:\Users\john\AppData\Local\R\win-library\4.6','C:\Users\john\AppData\Local\Programs\R\library') -TailscaleExecutable 'C:\Program Files\Tailscale\tailscale.exe'
    $phase = 'installed_acceptance_pending'
    Write-SetupReceipt 'installed_acceptance_pending'
    Write-Host 'Installation finished. Leave this window open; Codex will verify Python and R notebooks.' -ForegroundColor Green
} catch {
    Write-SetupReceipt 'failed' $_
    Write-Host ('Setup stopped during ' + $phase + '. Leave this window open; do not rerun.') -ForegroundColor Yellow
    Write-Host ('Error record: ' + $receiptPath)
}
