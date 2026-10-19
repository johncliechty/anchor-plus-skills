$ErrorActionPreference = 'Stop'
$probeRoot = 'C:\Users\john\AppData\Local\Temp\anchor-release-20260909\native-installer-probes-02'
if (Test-Path -LiteralPath $probeRoot) { throw 'Probe destination must be fresh.' }
$null = New-Item -ItemType Directory -Path $probeRoot
$currentSid = [Security.Principal.WindowsIdentity]::GetCurrent().User
$probeSid = [Security.Principal.SecurityIdentifier]::new('S-1-5-19')
$acl = [Security.AccessControl.DirectorySecurity]::new()
$acl.SetAccessRuleProtection($true, $false)
$acl.SetOwner($currentSid)
$acl.AddAccessRule([Security.AccessControl.FileSystemAccessRule]::new($currentSid,'FullControl','ContainerInherit,ObjectInherit','None','Allow'))
Set-Acl -LiteralPath $probeRoot -AclObject $acl
$child = Join-Path $probeRoot 'existing-child'
$null = New-Item -ItemType Directory -Path $child
$leaf = Join-Path $child 'existing.txt'
[IO.File]::WriteAllText($leaf,'Synthetic ACL probe only.')
$acl = Get-Acl -LiteralPath $probeRoot
$acl.AddAccessRule([Security.AccessControl.FileSystemAccessRule]::new($probeSid,'ReadAndExecute','ContainerInherit,ObjectInherit','None','Allow'))
Set-Acl -LiteralPath $probeRoot -AclObject $acl
$results = @()
foreach ($item in @($child,$leaf)) {
    $rules = @((Get-Acl -LiteralPath $item).GetAccessRules($true,$true,[Security.Principal.SecurityIdentifier]) | Where-Object { $_.IdentityReference.Value -eq $probeSid.Value -and $_.IsInherited -and $_.AccessControlType -eq 'Allow' })
    $rx = [Security.AccessControl.FileSystemRights]::ReadAndExecute
    $ok = @($rules | Where-Object { ($_.FileSystemRights -band $rx) -eq $rx }).Count -gt 0
    if (-not $ok) { throw 'Existing child did not receive inherited RX.' }
    $results += @{kind=if ($item -eq $child) {'directory'} else {'file'};inherited_rx=$ok}
}
$after = $false; $finallyRan = $false; $childExit = $null; $childDocument = $null
try {
    $childOutput = & 'C:\Users\john\AppData\Local\Temp\anchor-release-20260909\anchor\tools\install_notebook_startup.ps1' -Action Plan -PythonExecutable 'Z:\missing\python.exe' -ServiceScript 'Z:\missing\notebook_service.py' -SettingsFile 'Z:\missing\settings.json' -Account 'not-a-qualified-local-account'
    $childExit = $LASTEXITCODE
    $childDocument = ($childOutput -join [Environment]::NewLine) | ConvertFrom-Json
    $after = $true
} finally { $finallyRan = $true }
if (-not $after -or -not $finallyRan -or $childExit -ne 1 -or $childDocument.ok -ne $false -or $childDocument.error -ne 'exact_local_account_required') { throw 'Unexpected nested exit behavior.' }
$receipt = @{at=[DateTimeOffset]::UtcNow.ToString('o');acl_propagation=$results;nested_exit=@{caller_resumed=$after;caller_finally=$finallyRan;exit_code=$childExit;error=$childDocument.error};host_names=@{environment=$env:COMPUTERNAME;dns=[Net.Dns]::GetHostName()};live_paths_modified=$false}
$receipt | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath 'C:\dev\Anchor\planning\notebooks-model-routing-2026-09-08\installer-native-probes-2026-09-09.json' -Encoding UTF8
$receipt | ConvertTo-Json -Depth 5
