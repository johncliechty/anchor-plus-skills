# Private recovery for the positively identified pre-account password failure.
$ErrorActionPreference = 'Stop'
$receiptPath = Join-Path $PSScriptRoot 'password-recovery-result-2026-09-09.json'
# Refuse before entering the catch that writes a result: keep the first failure.
if (Test-Path -LiteralPath $receiptPath) {
    Write-Host 'This attempt already has a result. It was preserved; no setup action was taken.' -ForegroundColor Yellow
    return
}
$retainedPath = $null
function Write-SetupReceipt([string]$Status, [int]$Line=0, [string]$Message='') {
    $record=@{at=[DateTimeOffset]::UtcNow.ToString('o');status=$Status;pid=$PID;error_line=$Line;message=$Message;retained_preparation=$retainedPath}
    [IO.File]::WriteAllText($receiptPath,($record | ConvertTo-Json -Compress),[Text.UTF8Encoding]::new($false))
}
$Host.UI.RawUI.WindowTitle = 'Anchor notebook installation - retry password'
try {
    $admin=[Security.Principal.WindowsPrincipal]::new([Security.Principal.WindowsIdentity]::GetCurrent())
    if (-not $admin.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) { throw 'Run this recovery as administrator.' }
    Write-SetupReceipt 'validating_failed_preparation'
    $prior=Get-Content -LiteralPath (Join-Path $PSScriptRoot 'fixed-folder-setup-result-2026-09-09.json') -Raw -Encoding UTF8 | ConvertFrom-Json
    if ($prior.status -ne 'failed' -or $prior.pid -ne 23240 -or $prior.message -ne 'Passwords must match and contain at least 12 characters; no account was created.') { throw 'Expected pre-account password failure was not confirmed.' }
    $old=Get-CimInstance Win32_Process -Filter 'ProcessId=23240'
    if ($null -ne $old -and ($old.Name -ine 'powershell.exe' -or $old.CommandLine -notlike '*launch-local-setup-fixed-folder-2026-09-09.ps1*')) { throw 'Prior installer identity changed; no process was stopped.' }
    if (@(Get-LocalUser | Where-Object { $_.Name -ieq 'AnchorNotebook' }).Count) { throw 'Notebook account exists; recovery refused.' }
    if (@(Get-ScheduledTask | Where-Object { $_.TaskName -eq 'AnchorNotebookHost' }).Count) { throw 'Notebook task exists; recovery refused.' }
    if (Test-Path -LiteralPath 'C:\dev\Anchor\notebook-runtime.json') { throw 'Notebook runtime configuration exists; recovery refused.' }
    $install=[IO.Path]::GetFullPath('C:\ProgramData\AnchorNotebook')
    $item=Get-Item -LiteralPath $install -Force
    if (-not $item.PSIsContainer -or $item.FullName -ine $install -or ($item.Attributes -band [IO.FileAttributes]::ReparsePoint)) { throw 'Expected owned installation directory required.' }
    $ancestor=$item.Parent
    while ($null -ne $ancestor) {
        if ($ancestor.Attributes -band [IO.FileAttributes]::ReparsePoint) { throw 'Reparse ancestor refused.' }
        $ancestor=$ancestor.Parent
    }
    $entries=@(Get-ChildItem -LiteralPath $install -Force)
    if (@($entries | Where-Object { $_.Name -notin @('python','preparation.json') }).Count) { throw 'Unexpected installation state; recovery refused.' }
    $preparation=Get-Content -LiteralPath (Join-Path $install 'preparation.json') -Raw -Encoding UTF8 | ConvertFrom-Json
    if ($preparation.schema_version -ne 1 -or $preparation.status -ne 'runtime_preparation' -or $preparation.workspace -ine 'C:\dev\Teaching' -or $preparation.base_python -ine 'C:\Users\john\AppData\Local\Programs\Python\Python313\python.exe') { throw 'Preparation manifest does not match this authorized attempt.' }
    $retainedPath=[IO.Path]::GetFullPath('C:\ProgramData\AnchorNotebook-failed-password-'+[DateTime]::UtcNow.ToString('yyyyMMddTHHmmssZ'))
    if ([IO.Path]::GetDirectoryName($retainedPath) -ine 'C:\ProgramData' -or [IO.Path]::GetFileName($retainedPath) -notmatch '^AnchorNotebook-failed-password-\d{8}T\d{6}Z$' -or (Test-Path -LiteralPath $retainedPath)) { throw 'Fresh exact recovery destination required.' }
    if ($null -ne $old -and $old.ProcessId -ne $PID) { Stop-Process -Id 23240 }
    # Both absolute paths above are owned software locations under ProgramData.
    # The Teaching data tree is never moved or deleted.
    Move-Item -LiteralPath $install -Destination $retainedPath
    Write-SetupReceipt 'installing'
    Write-Host 'Software: C:\ProgramData\AnchorNotebook. Notebooks: C:\dev\Teaching.'
    Write-Host 'When prompted, enter the same password twice, with at least 12 characters.'
    Write-Host 'If they do not match, the prompt will let you try again.'
    # Only the prompt state is recorded; SecureString values stay in this process.
    function Read-Host([string]$Prompt, [switch]$AsSecureString) {
        if (-not $AsSecureString) { throw 'Only a secure local prompt is expected.' }
        Write-SetupReceipt 'awaiting_private_password'
        $localSecret=Microsoft.PowerShell.Utility\Read-Host -Prompt $Prompt -AsSecureString
        Write-SetupReceipt 'installing'
        return $localSecret
    }
    & 'C:\dev\Anchor\tools\setup_notebooks.ps1' -PythonExecutable 'C:\Users\john\AppData\Local\Programs\Python\Python313\python.exe' -AnchorDataDirectory 'C:\dev\Anchor' -PublicBaseUrl 'https://gwl-server.tailb49f65.ts.net:8448/' -NotebookRoot 'C:\dev\Teaching' -RExecutable 'C:\Users\john\AppData\Local\Programs\R\bin\R.exe' -RLibraryDirectories @('C:\Users\john\AppData\Local\R\win-library\4.6','C:\Users\john\AppData\Local\Programs\R\library') -TailscaleExecutable 'C:\Program Files\Tailscale\tailscale.exe'
    Write-SetupReceipt 'installed_acceptance_pending'
    Write-Host 'Installation finished. Codex will verify notebook execution and opening.'
} catch {
    Write-SetupReceipt 'failed' $_.InvocationInfo.ScriptLineNumber $_.Exception.Message
    Write-Host 'Setup stopped. Leave this window open for Codex to inspect the safe result.' -ForegroundColor Yellow
}
