# Read-only diagnosis of the retained setup; writes only this session's diagnostic receipt.
$ErrorActionPreference = 'Stop'
$destination = Join-Path $PSScriptRoot 'notebook-startup-diagnostic-2026-09-10.json'
if (Test-Path -LiteralPath $destination) {
    Write-Host ('Diagnostic already saved: ' + $destination)
    return
}
$identity = [Security.Principal.WindowsIdentity]::GetCurrent()
if (-not ([Security.Principal.WindowsPrincipal]::new($identity)).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    Write-Host 'Run this in the Administrator PowerShell window.' -ForegroundColor Yellow
    return
}
$record = @{at=[DateTimeOffset]::UtcNow.ToString('o');pid=$PID;status='diagnosing'}
try {
    $install = 'C:\ProgramData\AnchorNotebook'
    $expectedSid = 'S-1-5-21-2519451599-2226736531-398949285-1008'
    $receipt = Get-Content -LiteralPath (Join-Path $install 'installation.json') -Raw -Encoding UTF8 | ConvertFrom-Json
    $account = $env:COMPUTERNAME + '\AnchorNotebook'
    $user = Get-LocalUser -Name 'AnchorNotebook'
    if ($receipt.schema_version -ne 1 -or $receipt.status -ne 'provisioning' -or $receipt.account_sid -ne $expectedSid -or $user.SID.Value -ne $expectedSid -or $receipt.account -ine $account -or $receipt.workspace -ine 'C:\dev\Teaching' -or $receipt.task -ne 'AnchorNotebookHost') { throw 'Owned notebook account and installation receipt must match.' }
    $record.account_sid = $expectedSid
    $record.account_enabled = $user.Enabled
    # Administrator-only tasks may be invisible to the ordinary session.
    $record.tasks = @(Get-ScheduledTask | Where-Object { $_.TaskName -eq 'AnchorNotebookHost' } | ForEach-Object {
        @{name=$_.TaskName;path=$_.TaskPath;state=$_.State.ToString();account=$_.Principal.UserId;enabled=$_.Settings.Enabled}
    })
    $startup = 'C:\dev\Anchor\tools\install_notebook_startup.ps1'
    $verified = Get-Content -LiteralPath (Join-Path $PSScriptRoot 'startup-diagnostic-verified-source-2026-09-10.json') -Raw -Encoding UTF8 | ConvertFrom-Json
    if ($verified.status -ne 'passed' -or (Get-FileHash -LiteralPath $startup -Algorithm SHA256).Hash -ine $verified.sha256) { throw 'Diagnostic entrypoint must match its verified source.' }
    $record.startup_sha256 = $verified.sha256
    $result = @(& $startup -Action Validate -PythonExecutable (Join-Path $install 'python\Scripts\python.exe') -ServiceScript (Join-Path $install 'app\notebook_service.py') -SettingsFile (Join-Path $install 'private\service-settings.json') -Account $account)
    $document = ($result -join [Environment]::NewLine) | ConvertFrom-Json
    $record.validation = $document
    if ($document.PSObject.Properties['validation_path'] -and $document.validation_path) {
        $path = [IO.Path]::GetFullPath([string]$document.validation_path)
        $acl = Get-Acl -LiteralPath $path
        $record.checked_acl = @{path=$path;owner=$acl.GetOwner([Security.Principal.SecurityIdentifier]).Value;protected=$acl.AreAccessRulesProtected;rules=@($acl.GetAccessRules($true,$true,[Security.Principal.SecurityIdentifier]) | ForEach-Object {
            @{sid=$_.IdentityReference.Value;rights=$_.FileSystemRights.ToString();type=$_.AccessControlType.ToString();inherited=$_.IsInherited;inheritance=$_.InheritanceFlags.ToString();propagation=$_.PropagationFlags.ToString()}
        })}
    }
    $record.status = 'diagnosed'
} catch {
    $record.status = 'diagnostic_failed'
    $record.error_type = $_.Exception.GetType().FullName
    $record.error_id = $_.FullyQualifiedErrorId
    $record.error_line = $_.InvocationInfo.ScriptLineNumber
} finally {
    $json = $record | ConvertTo-Json -Depth 10
    $stream = [IO.File]::Open($destination,[IO.FileMode]::CreateNew,[IO.FileAccess]::Write,[IO.FileShare]::None)
    try {
        $bytes = [Text.UTF8Encoding]::new($false).GetBytes($json)
        $stream.Write($bytes,0,$bytes.Length)
    } finally { $stream.Dispose() }
}
Write-Host 'Diagnostic saved. No account, password, permissions, or startup task was changed.'
Write-Host ('Result: ' + $destination)
